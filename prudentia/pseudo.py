"""P3 가명화·복원. 결정론만 쓴다(LLM이 토큰을 정하지 않는다).

- 가명 맵(PseudoMap): 토큰 하나 ↔ 여러 표기(surfaces). 파일로 저장돼 다음 주에도 같은 토큰을 쓴다.
- 복원표(restore): mask 한 번마다 "토큰이 나온 순서대로 원래 표기"를 기록.
  같은 토큰이 문서 안에서 다른 표기(한서윤 / ハン・ソユン)였어도 원문과 바이트 단위로 똑같이 되돌린다.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

from .spans import Span

# [PERSON_001] (가명 맵), [COMPONENT_01] (용어집), [COMPONENT_01: 작업 우선순위 스케줄러] (L1 설명형 별칭)
TOKEN_RE = re.compile(r"\[([A-Z_]+)_(\d{2,})(?::[^\[\]\n]{0,80})?\]")


def canonical(token_text: str) -> str:
    """'[COMPONENT_01: 설명]' → '[COMPONENT_01]'. 복원은 설명이 아니라 id로 한다(외부 LLM이 설명을 바꿔 써도 복원됨)."""
    m = TOKEN_RE.fullmatch(token_text)
    return f"[{m.group(1)}_{m.group(2)}]" if m else token_text


def norm(surface: str) -> str:
    """표기 비교용 정규화: 전각/반각 통일, 대소문자 무시, 공백·가운뎃점 제거."""
    s = unicodedata.normalize("NFKC", surface).casefold()
    return re.sub(r"[\s・·.\-_]", "", s)


class PseudoMap:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {"version": 1, "counters": {}, "entities": {}}
        self.counters: dict[str, int] = data["counters"]
        self.entities: dict[str, dict] = data["entities"]
        # 교차 표기 연결용 로마자 캐시 {표기: {"family","given","nationality"}} — 새 표기만 LLM을 부르게
        self.romanized: dict[str, dict] = data.get("romanized", {})
        self._index = {}  # (type, norm(surface)) -> token
        for tok, ent in self.entities.items():
            for s in ent["surfaces"]:
                self._index[(ent["type"], norm(s))] = tok

    def lookup(self, typ: str, surface: str) -> str | None:
        return self._index.get((typ, norm(surface)))

    def token_for(self, typ: str, surface: str, aliases: list[str] = ()) -> str:
        """표기에 맞는 토큰을 돌려준다. 없으면 aliases(같은 사람이라고 연결된 다른 표기)의 토큰, 그것도 없으면 새로 만든다."""
        tok = self.lookup(typ, surface)
        if tok is None:
            for a in aliases:
                tok = self.lookup(typ, a)
                if tok:
                    break
        if tok is None:
            n = self.counters.get(typ, 0) + 1
            self.counters[typ] = n
            tok = f"[{typ}_{n:03d}]"
            self.entities[tok] = {"type": typ, "surfaces": []}
        if surface not in self.entities[tok]["surfaces"]:
            self.entities[tok]["surfaces"].append(surface)
        self._index[(typ, norm(surface))] = tok
        return tok

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = {"version": 1, "counters": self.counters, "entities": self.entities, "romanized": self.romanized}
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)  # 중간에 끊겨도 맵이 반쯤 쓰이지 않게


def mask(text: str, spans: list[Span], pmap: PseudoMap, links: dict[str, list[str]] | None = None):
    """spans(겹침 정리된 것)를 토큰으로 바꾼다. → (가명화된 텍스트, 복원표)

    links: {표기: [같은 사람의 다른 표기, ...]} — P4 LLM의 교차 표기 연결 제안.
    용어집 스팬(meta 있음)은 가명 맵을 쓰지 않고 용어집이 정한 토큰·모양(render)을 쓴다.
    """
    if TOKEN_RE.search(text):
        raise ValueError("원문에 이미 [TYPE_01] 형태의 문자열이 있어 복원이 모호해집니다.")
    links = links or {}
    out, restore, pos = [], [], 0
    for s in sorted(spans, key=lambda s: s.start):
        surface = text[s.start:s.end]
        if s.meta:
            tok, shown = s.meta["token"], s.meta["render"]
        else:
            tok = shown = pmap.token_for(s.type, surface, links.get(surface, []))
        out.append(text[pos:s.start])
        out.append(shown)
        restore.append({"token": tok, "surface": surface})
        pos = s.end
    out.append(text[pos:])
    return "".join(out), restore


def unmask(masked: str, restore: list[dict], pmap: PseudoMap | None = None) -> str:
    """토큰을 원래 표기로 되돌린다.

    토큰이 나온 순서대로 복원표의 표기를 쓴다(라운드트립이면 원문과 완전히 같다).
    외부 LLM이 토큰을 더 많이 쓰거나 순서를 바꾼 경우: 이 문서에서 그 토큰의 첫 표기를 쓴다.
    이 문서에 없던 토큰이면 가명 맵의 첫 표기, 그것도 없으면 토큰 그대로 둔다.
    """
    queues: dict[str, list[str]] = {}
    first: dict[str, str] = {}
    for r in restore:
        queues.setdefault(r["token"], []).append(r["surface"])
        first.setdefault(r["token"], r["surface"])

    def repl(m: re.Match) -> str:
        tok = canonical(m.group(0))
        if queues.get(tok):
            return queues[tok].pop(0)
        if tok in first:
            return first[tok]
        if pmap and tok in pmap.entities and pmap.entities[tok]["surfaces"]:
            return pmap.entities[tok]["surfaces"][0]
        return tok

    return TOKEN_RE.sub(repl, masked)
