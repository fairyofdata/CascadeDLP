"""P4 로컬 LLM 층 (Ollama). 형식 없는 것만 맡긴다.

1. detect(): 사람 이름·주소·조직명 '후보 문자열'을 받는다. 위치(start/end)는 코드가 원문에서 찾아 정한다
   → 원문에 없는 문자열(환각)은 자동으로 버려진다.
2. link(): 이름 표기 목록을 주면 '같은 사람끼리' 묶음을 제안받는다. 토큰 부여는 pseudo.py가 한다.

프롬프트를 바꾸면 PROMPT_VERSION을 올린다(결과표에 같이 기록됨).
"""
import json
import re
import time

import requests

from .spans import Span

# v1: 탐지 + 연결(표기 목록 전체를 한 번에 묶게 함)
# v2: 탐지 프롬프트 동일 + 조각 병합·호칭 제거 후처리, 연결은 romanize()(표기마다 로마자 발음) + linking.py가 판정
# v3: 프롬프트 동일. eval_v2 결과를 보고 후처리(명단 병합 금지)·연결 판정(성 비교 완화)·규칙(전화 형식) 수정
# v4: 프롬프트 동일. C1 — 비밀키 규칙(SECRET) 추가, 프로젝트 용어집 스팬이 LLM보다 우선
# v5: 프롬프트 동일. 개인정보 탐지 조각 300자(gate.DETECT_CHUNK_CHARS), 숫자·시각만인 LLM 스팬 제거
PROMPT_VERSION = "v5"
OLLAMA_URL = "http://localhost:11434/api/chat"
OPTIONS = {"temperature": 0, "num_ctx": 8192}
LLM_TYPES = ["PERSON", "ADDRESS", "ORG"]

DETECT_SYSTEM = """You find personal information in Korean / Japanese / English (often mixed) text.
Extract every:
- PERSON: a person's name (full name, given name only, or family name only), in any script (Hangul, Kanji, Kana, Latin).
- ADDRESS: a street address or address fragment more specific than a city (district, street, block number).
- ORG: a company or organization name.
Rules:
- Copy each item EXACTLY as it appears in the text (same characters, same spacing).
- Do NOT include honorifics or particles: さん, 様, ちゃん, 씨, 님, 이가, 이, 가, Mr., etc.
- Do NOT extract emails, phone numbers, URLs, postal codes, dates, or ID numbers.
- Do NOT extract country or city names alone (e.g. 서울, 大阪, Osaka), or common words.
- If there is nothing, return an empty list."""

DETECT_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "type": {"type": "string", "enum": LLM_TYPES}},
                "required": ["text", "type"],
            },
        }
    },
    "required": ["entities"],
}

LINK_SYSTEM = """You are given a numbered list of person-name spellings collected from Korean / Japanese / English documents.
The same person may appear in Hangul, Kanji, Katakana, Hiragana, or romanized Latin letters,
with family name first or last, or with only the given name or family name.
Group the numbers that refer to the SAME person. Every number must appear in exactly one group.
Put a spelling in its own group if you are not confident. Different people must never share a group."""

LINK_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}}},
    "required": ["groups"],
}


ROMANIZE_SYSTEM = """You are given one person's name as written in a Korean / Japanese / English document.
It may be in Hangul, Kanji/Hanja, Katakana, Hiragana, or Latin letters, in any order (family-given or given-family),
or only the family name or only the given name.
Return how it is PRONOUNCED, in lowercase Latin letters, split into family name and given name.
- Korean names (including Korean names written in Hanja or Katakana): Revised Romanization, but use the common
  family-name spellings: kim, lee, park, choi, jung, kang, han, baek, yoon.
- Japanese names: Hepburn without long-vowel marks (sato, not satou or satō).
- Western names: as written.
- If only one part is present, leave the other part as an empty string.
- nationality: "korean", "japanese", "other", or "unknown"."""

ROMANIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "family": {"type": "string"},
        "given": {"type": "string"},
        "nationality": {"type": "string", "enum": ["korean", "japanese", "other", "unknown"]},
    },
    "required": ["family", "given", "nationality"],
}


def romanize(surface: str, model: str) -> dict:
    """이름 표기 하나 → {"family", "given", "nationality"} (로마자 발음). 판정은 linking.py가 한다."""
    try:
        out = _chat(model, ROMANIZE_SYSTEM, surface, ROMANIZE_SCHEMA)
    except (json.JSONDecodeError, KeyError):
        out = {}
    return {k: str(out.get(k, "")).strip().lower() for k in ("family", "given", "nationality")}


def _chat(model: str, system: str, user: str, schema: dict) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "think": False,
        "options": OPTIONS,
    }
    r = requests.post(OLLAMA_URL, json=body, timeout=600)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def detect(text: str, model: str) -> tuple[list[Span], float]:
    """LLM 후보 → 원문에서 위치를 찾은 스팬 목록, 걸린 시간(초)."""
    t0 = time.perf_counter()
    try:
        out = _chat(model, DETECT_SYSTEM, text, DETECT_SCHEMA)
    except (json.JSONDecodeError, KeyError):
        out = {"entities": []}  # 형식이 깨지면 이 문장은 LLM 기여 없음으로 처리
    elapsed = time.perf_counter() - t0
    spans = []
    for e in out.get("entities", []):
        cand, typ = e.get("text", "").strip(), e.get("type")
        if not cand or typ not in LLM_TYPES:
            continue
        i = text.find(cand)
        while i != -1:  # 같은 문자열이 여러 번 나오면 모두
            spans.append(Span(i, i + len(cand), typ, "llm"))
            i = text.find(cand, i + len(cand))
    return tidy(text, spans), elapsed


# 이름 뒤에 붙는 호칭 (스팬 끝에 붙어 있으면 잘라낸다)
HONORIFICS = ("ちゃん", "さん", "くん", "様", "さま", "씨", "님")
_JOINERS = {"PERSON": " ・·", "ADDRESS": " ,、", "ORG": " "}


def tidy(text: str, spans: list[Span]) -> list[Span]:
    """LLM 스팬 후처리(결정론).
    1) 같은 유형 스팬이 공백·가운뎃점 등으로만 떨어져 있으면 하나로 합친다 (Seoyun + Han → Seoyun Han)
       단 이름이 3조각 이상이면 명단으로 보고 합치지 않는다. 2명이 공백으로만 붙은 명단(정민호 김민준)은 합쳐지는 한계가 있다.
    2) PERSON 끝의 호칭을 잘라낸다 (春ちゃん → 春). 한국어 '하늘이가'처럼 이름 뒤 '이'+조사도 '이'를 뗀다.
    """
    spans = sorted({(s.start, s.end, s.type): s for s in spans}.values(), key=lambda s: (s.start, -s.end))
    merged: list[Span] = []
    pieces: list[int] = []  # merged[i]가 몇 조각으로 합쳐졌나
    for s in spans:
        if merged:
            p = merged[-1]
            gap = text[p.end:s.start]
            if p.type == s.type and s.start >= p.end and gap and all(c in _JOINERS[s.type] for c in gap):
                p.end = max(p.end, s.end)
                pieces[-1] += 1
                continue
            if s.start < p.end:  # 겹치면 긴 쪽(앞 스팬)을 남긴다
                p.end = max(p.end, s.end) if p.type == s.type else p.end
                continue
        merged.append(Span(s.start, s.end, s.type, s.source))
        pieces.append(1)
    # 이름이 3조각 이상 공백으로 이어졌으면 '성+이름'이 아니라 명단(정민호 김민준 오세린) → 합치지 않고 되돌린다
    if any(n >= 3 and m.type == "PERSON" for m, n in zip(merged, pieces)):
        out = []
        for m, n in zip(merged, pieces):
            if m.type == "PERSON" and n >= 3:
                out += [Span(s.start, s.end, s.type, s.source) for s in spans if m.start <= s.start and s.end <= m.end]
            else:
                out.append(m)
        merged = out
    merged = [s for s in merged if not _NUMERIC_ONLY.fullmatch(text[s.start:s.end])]
    return _strip_honorifics(text, merged)


# 숫자·시각·기호만으로 된 LLM 스팬(예: '04:30'을 ADDRESS로)은 버린다 — 형식 있는 번호는 규칙 층이 맡는다(C6에서 발견)
_NUMERIC_ONLY = re.compile(r"[\d\s:.,/~\-%()]+")


def _strip_honorifics(text: str, merged: list[Span]) -> list[Span]:
    for s in merged:
        if s.type != "PERSON":
            continue
        surface = text[s.start:s.end]
        for h in HONORIFICS:
            if surface.endswith(h) and len(surface) > len(h):
                s.end -= len(h)
                break
        else:
            if surface.endswith("이") and len(surface) >= 3 and text[s.end:s.end + 1] in ("가", "는", "를", "도", "랑", "한"):
                s.end -= 1
    return merged


def link(surfaces: list[str], model: str) -> tuple[list[list[int]], float]:
    """표기 목록 → 같은 사람 묶음(인덱스 목록들). 잘못된 출력은 코드가 바로잡는다."""
    t0 = time.perf_counter()
    user = "\n".join(f"{i}: {s}" for i, s in enumerate(surfaces))
    try:
        groups = _chat(model, LINK_SYSTEM, user, LINK_SCHEMA).get("groups", [])
    except (json.JSONDecodeError, KeyError):
        groups = []
    elapsed = time.perf_counter() - t0
    seen, clean = set(), []
    for g in groups:  # 범위 밖·중복 번호 제거
        g2 = [i for i in g if isinstance(i, int) and 0 <= i < len(surfaces) and i not in seen]
        seen.update(g2)
        if g2:
            clean.append(g2)
    clean += [[i] for i in range(len(surfaces)) if i not in seen]  # 빠진 번호는 혼자 묶음
    return clean, elapsed
