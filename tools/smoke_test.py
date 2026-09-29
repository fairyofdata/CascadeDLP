"""Ollama가 응답하고, JSON 스키마 형식 출력을 지키는지 1회 확인한다.

입력 문장은 합성 예문이다(실존 인물·연락처 아님).
"""
import json
import sys
import time

import requests

URL = "http://localhost:11434/api/chat"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:8b"

SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": ["PERSON", "ADDRESS", "ORG", "OTHER"]},
                },
                "required": ["text", "type"],
            },
        }
    },
    "required": ["entities"],
}

SAMPLE = "昨日、김서연さんと Tanaka Haruto から連絡があり、岡山市北区の事務所で会う予定です。"

body = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "Extract personal names and addresses from the text. Return JSON only."},
        {"role": "user", "content": SAMPLE},
    ],
    "format": SCHEMA,
    "stream": False,
    "think": False,
    "options": {"temperature": 0, "num_ctx": 8192},
}

t0 = time.perf_counter()
r = requests.post(URL, json=body, timeout=300)
r.raise_for_status()
elapsed = time.perf_counter() - t0
content = r.json()["message"]["content"]
parsed = json.loads(content)  # 형식이 깨지면 여기서 예외
print(f"model={MODEL}  {elapsed:.1f}s")
print(json.dumps(parsed, ensure_ascii=False, indent=1))
print("OK")
