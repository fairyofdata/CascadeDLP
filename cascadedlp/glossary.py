"""C1 프로젝트 용어집: "이 프로젝트에서만 특별한 말"을 사람이 적어 두고, 적힌 대로 결정론으로 찾는다.

파일: ~/.cascadedlp/projects/<프로젝트>/glossary.json  (가명 맵만큼 민감 — 저장소·MCP 밖)
{
  "project": "tessellane",
  "entries": [
    {"id": "COMPONENT_01", "kind": "COMPONENT", "level": 1, "status": "confirmed",
     "surfaces": ["Adaptive Scheduler", "조율기", "適応スケジューラ"],
     "alias": "작업 우선순위 스케줄러"}
  ]
}
레벨: 0 공개(그대로) · 1 내부(설명형 별칭) · 2 핵심(불투명 토큰) · 3 외부 금지(클라우드용 생성 거부)
status가 "confirmed"가 아니면(LLM 제안 등) 레벨을 최소 2로 올려 보수적으로 다룬다.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .spans import Span

KINDS = {"PROJECT", "COMPONENT", "ALGORITHM", "TERM", "ORG", "PERSON", "SECRET"}
_SEP = r"[\s_\-・·.]?"             # 표기 사이에 끼어도 되는 구분자 (Adaptive Scheduler = adaptive_scheduler = AdaptiveScheduler)
_LATIN = re.compile(r"[A-Za-z0-9]")


@dataclass
class Entry:
    id: str
    kind: str
    level: int
    surfaces: list[str]
    alias: str = ""
    status: str = "proposed"

    @property
    def effective_level(self) -> int:
        return self.level if self.status == "confirmed" else max(self.level, 2)

    @property
    def token(self) -> str:
        return f"[{self.id}]"

    def render(self) -> str:
        """밖으로 나갈 모양. L1은 설명을 붙여 의미를 남긴다."""
        if self.effective_level == 1 and self.alias:
            return f"[{self.id}: {self.alias}]"
        return self.token


def _units(surface: str) -> list[str]:
    """표기를 단위로 쪼갠다: 공백·_·-·가운뎃점, 그리고 CamelCase 경계에서."""
    parts = re.split(r"[\s_\-・·.]+", surface.strip())
    out = []
    for p in parts:
        out += re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+|[^A-Za-z\d]+", p) or [p]
    return [u for u in out if u]


def surface_pattern(surface: str) -> str:
    units = _units(surface)
    body = _SEP.join(re.escape(u) for u in units)
    # 영문·숫자로 시작/끝나면 단어 경계를 지킨다 (Atlas가 Atlassian 안에서 잡히지 않게)
    if _LATIN.match(units[0][0]):
        body = r"(?<![A-Za-z0-9])" + body
    if _LATIN.match(units[-1][-1]):
        body = body + r"(?![A-Za-z0-9])"
    return body


class Glossary:
    def __init__(self, entries: list[Entry], project: str = ""):
        self.project = project
        self.entries = entries
        self.problems = self._validate()
        # 긴 표기부터 시도해야 'Adaptive Scheduler'가 'Scheduler'보다 먼저 잡힌다
        pats = sorted(((s, e) for e in entries for s in e.surfaces), key=lambda x: -len(x[0]))
        self._compiled = [(re.compile(surface_pattern(s), re.IGNORECASE), e) for s, e in pats]

    @classmethod
    def load(cls, path: str | Path) -> "Glossary":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [Entry(id=x["id"], kind=x["kind"], level=int(x["level"]), surfaces=list(x["surfaces"]),
                         alias=x.get("alias", ""), status=x.get("status", "proposed")) for x in data["entries"]]
        return cls(entries, data.get("project", Path(path).parent.name))

    @classmethod
    def empty(cls) -> "Glossary":
        return cls([])

    def _validate(self) -> list[str]:
        problems, seen = [], {}
        for e in self.entries:
            if not re.fullmatch(r"[A-Z_]+_\d{2,}", e.id):
                problems.append(f"{e.id}: id는 KIND_01 형식이어야 함")
            if e.kind not in KINDS:
                problems.append(f"{e.id}: 알 수 없는 kind {e.kind}")
            if e.level not in (0, 1, 2, 3):
                problems.append(f"{e.id}: level은 0~3")
            if e.effective_level == 1 and not e.alias:
                problems.append(f"{e.id}: L1은 alias(설명)가 필요함")
            for s in e.surfaces:
                key = s.casefold()
                if key in seen and seen[key] != e.id:
                    problems.append(f"표기 '{s}'가 {seen[key]}와 {e.id}에 중복")
                seen[key] = e.id
        return problems

    def match(self, text: str) -> list[Span]:
        """용어집 표기가 나온 곳을 모두 찾는다(서로 겹치지 않게, 긴 표기 우선)."""
        taken: list[tuple[int, int]] = []
        spans = []
        for pat, e in self._compiled:
            for m in pat.finditer(text):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                spans.append(Span(m.start(), m.end(), e.kind, "glossary", entity_id=e.id,
                                  meta={"token": e.token, "render": e.render(), "level": e.effective_level}))
        return sorted(spans, key=lambda s: s.start)
