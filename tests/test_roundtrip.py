"""P3 기준: mask → unmask 결과가 원문과 바이트 단위로 같아야 한다. (LLM 없이, 정답 스팬으로 검사)"""
import json
from pathlib import Path

import pytest

from cascadedlp import cli
from cascadedlp.pseudo import PseudoMap, mask, unmask
from cascadedlp.spans import Span, resolve

EVAL = Path(__file__).parent.parent / "data" / "eval" / "eval_v1.jsonl"
ROWS = [json.loads(l) for l in EVAL.read_text(encoding="utf-8").splitlines()]


def gold_spans(row):
    return [Span(s["start"], s["end"], s["type"], "gold") for s in row["spans"]]


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_roundtrip_gold(row, tmp_path):
    pmap = PseudoMap(tmp_path / "m.json")
    masked, restore = mask(row["text"], gold_spans(row), pmap)
    for s in row["spans"]:  # 원래 값이 가명화 텍스트에 남아 있으면 안 된다
        assert row["text"][s["start"]:s["end"]] not in masked
    assert unmask(masked, restore).encode("utf-8") == row["text"].encode("utf-8")


def test_same_token_across_runs(tmp_path):
    """오늘 [PERSON_001]이던 사람은 맵을 다시 읽어도 [PERSON_001]."""
    p = tmp_path / "m.json"
    m1 = PseudoMap(p)
    a, _ = mask("한서윤 님", [Span(0, 3, "PERSON")], m1)
    m1.save()
    m2 = PseudoMap(p)
    b, _ = mask("김철수와 한서윤", [Span(0, 3, "PERSON"), Span(5, 8, "PERSON")], m2)
    assert a == "[PERSON_001] 님"
    assert b == "[PERSON_002]와 [PERSON_001]"


def test_linked_surfaces_share_token_and_restore_exactly(tmp_path):
    """교차 표기가 한 토큰으로 묶여도, 복원은 문서에 있던 표기 그대로."""
    text = "한서윤(ハン・ソユン)"
    pmap = PseudoMap(tmp_path / "m.json")
    masked, restore = mask(text, [Span(0, 3, "PERSON"), Span(4, 10, "PERSON")], pmap,
                           links={"ハン・ソユン": ["한서윤"], "한서윤": ["ハン・ソユン"]})
    assert masked == "[PERSON_001]([PERSON_001])"
    assert unmask(masked, restore) == text


def test_unmask_llm_answer_reuses_tokens(tmp_path):
    pmap = PseudoMap(tmp_path / "m.json")
    masked, restore = mask("박민재 과장", [Span(0, 3, "PERSON")], pmap)
    answer = "[PERSON_001]님께 전달했습니다. [PERSON_001]님이 확인 예정."  # 외부 LLM이 토큰을 두 번 씀
    assert unmask(answer, restore) == "박민재님께 전달했습니다. 박민재님이 확인 예정."


def test_rejects_text_with_token_like_string(tmp_path):
    with pytest.raises(ValueError):
        mask("[PERSON_001] 은 예시", [], PseudoMap(tmp_path / "m.json"))


def test_cli_roundtrip_bytes(tmp_path, capsys):
    """CLI 경유(규칙만), CRLF 줄바꿈 포함 파일도 바이트 일치."""
    src = tmp_path / "in.txt"
    src.write_bytes("메일 a.b@example.com\r\n電話 090-3712-5584\r\n".encode("utf-8"))
    home = ["--home", str(tmp_path / "home"), "--rules-only"]
    cli.main(home + ["mask", str(src), "-o", str(tmp_path / "out.txt")])
    job = next(l.split()[1] for l in capsys.readouterr().out.splitlines() if l.startswith("job:"))
    assert "example.com" not in (tmp_path / "out.txt").read_text(encoding="utf-8")
    cli.main(home + ["unmask", str(tmp_path / "out.txt"), "--job", job, "-o", str(tmp_path / "back.txt")])
    assert (tmp_path / "back.txt").read_bytes() == src.read_bytes()


def test_resolve_prefers_rule_then_longer():
    s = resolve([Span(0, 5, "PERSON", "llm"), Span(3, 10, "EMAIL", "rule"), Span(0, 2, "PERSON", "llm")])
    assert [(x.start, x.end, x.type) for x in s] == [(0, 2, "PERSON"), (3, 10, "EMAIL")]
