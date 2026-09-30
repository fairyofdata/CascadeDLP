"""P5: 가명화된 텍스트를 로컬 LLM으로 번역·요약 → 외부 LLM에 보낼 양을 줄인다.

핵심 위험은 토큰이 망가지는 것([PERSON_001] → [PERSON_1], 【PERSON_001】, 'PERSON 001', 사라짐, 새로 지어냄).
- translate()/summarize(): LLM 호출 (P5_PROMPT_VERSION)
- repair_tokens(): 망가진 토큰을 '입력에 있던 토큰'으로만 되돌린다(결정론). 입력에 없던 토큰은 만들지 않는다.
- token_report(): 입력 대비 보존·누락·지어냄·변형 개수
"""
import re
from collections import Counter

import requests

from .llm import OLLAMA_URL
from .pseudo import TOKEN_RE

P5_PROMPT_VERSION = "p5-v1"
LANG_NAME = {"ko": "Korean", "ja": "Japanese", "en": "English"}

RULE = ("The text contains placeholder tokens like [PERSON_001], [EMAIL_002], [ADDRESS_001]. "
        "Copy every token EXACTLY as written: same square brackets, same uppercase type, same 3-digit number. "
        "Never translate, rename, renumber, remove the brackets, or replace a token with a real-looking name. "
        "Do not add tokens that are not in the input. Keep particles/honorifics outside the token (e.g. [PERSON_001]さん, [PERSON_001] 님).")


def _gen(model: str, system: str, text: str, temperature: float = 0.2) -> str:
    body = {"model": model, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
            "options": {"temperature": temperature, "num_ctx": 8192}}
    r = requests.post(OLLAMA_URL, json=body, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def translate(masked: str, target: str, model: str) -> str:
    system = f"Translate the user's text into natural {LANG_NAME[target]}. Output only the translation.\n{RULE}"
    return _gen(model, system, masked)


def summarize(masked: str, lang: str, model: str) -> str:
    system = (f"Summarize the user's text in {LANG_NAME[lang]} in 3-5 bullet points. Keep who did what "
              f"(refer to people by their tokens). Output only the summary.\n{RULE}")
    return _gen(model, system, masked)


# 망가진 토큰 모양: 괄호 종류가 다르거나 없음, 숫자 자릿수 다름, 공백·전각 밑줄
_LOOSE = re.compile(r"(?:[\[【［「〔(]\s*)?([A-Z]+(?:_[A-Z]+)*)[\s_＿]?(\d{1,4})(?:\s*[\]】］」〕)])?")


_KINDS = ("PERSON", "EMAIL", "PHONE", "ADDRESS", "ORG", "URL", "POSTAL", "ID_NUMBER",
          "PROJECT", "COMPONENT", "ALGORITHM", "TERM", "SECRET")


def repair_tokens(output: str, input_tokens: set[str]) -> str:
    """망가진 토큰을 입력에 있던 정확한 토큰으로 되돌린다. 입력에 없던 토큰이 되는 경우는 건드리지 않는다."""
    def fix(m: re.Match) -> str:
        for width in (3, 2):  # 가명 맵은 3자리([PERSON_001]), 용어집은 2자리([COMPONENT_01])
            cand = f"[{m.group(1)}_{int(m.group(2)):0{width}d}]"
            if cand in input_tokens:
                return cand
        return m.group(0)

    # 이미 올바른 토큰([X_01], [X_01: 설명])은 건드리지 않고, 그 사이 구간에서만 보정한다
    out, pos = [], 0
    for t in TOKEN_RE.finditer(output):
        out.append(_LOOSE.sub(fix, output[pos:t.start()]))
        out.append(t.group(0))
        pos = t.end()
    out.append(_LOOSE.sub(fix, output[pos:]))
    return "".join(out)


def token_report(input_text: str, output: str) -> dict:
    src = Counter(TOKEN_RE.findall(input_text))
    src_set = {f"[{t}_{n}]" for t, n in src}
    out_tokens = [f"[{t}_{n}]" for t, n in TOKEN_RE.findall(output)]
    out_set = set(out_tokens)
    outside = TOKEN_RE.sub(" ", output)  # 올바른 토큰을 지운 나머지에서만 망가진 모양을 찾는다
    malformed = [m.group(0) for m in _LOOSE.finditer(outside) if any(k in m.group(0) for k in _KINDS)]
    return {
        "input_unique": len(src_set),
        "preserved_unique": len(src_set & out_set),       # 입력 토큰 종류 중 출력에 그대로 있는 것
        "missing": sorted(src_set - out_set),
        "invented": sorted(out_set - src_set),            # 입력에 없던 토큰 (위험: 복원 시 다른 사람으로 바뀜)
        "malformed": malformed,                           # 모양이 망가진 토큰 (복원이 안 됨)
    }
