"""스팬(Span) = 텍스트 안의 한 구간 [start, end) 과 그 유형.

규칙·LLM 등 여러 탐지기가 낸 스팬이 겹칠 수 있으므로 resolve()로 하나만 남긴다.
"""
from dataclasses import dataclass, field


@dataclass
class Span:
    start: int
    end: int
    type: str
    source: str = "rule"          # "rule" | "llm" | "gold"
    entity_id: str | None = field(default=None, compare=False)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


# 겹칠 때 누가 이기나: 규칙(형식이 확실함) > LLM, 그다음 긴 쪽
_SOURCE_RANK = {"rule": 0, "gold": 0, "llm": 1}


def resolve(spans: list[Span]) -> list[Span]:
    """겹치는 스팬을 정리해 서로 겹치지 않는 목록을 시작 위치 순으로 돌려준다."""
    ranked = sorted(spans, key=lambda s: (_SOURCE_RANK.get(s.source, 9), -(s.end - s.start), s.start))
    kept: list[Span] = []
    for s in ranked:
        if not any(s.overlaps(k) for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s.start)
