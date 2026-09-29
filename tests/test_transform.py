"""P5 결정론 부분: 망가진 토큰 보정, 토큰 보고서."""
from piigate.transform import repair_tokens, token_report

IN = "[PERSON_001]さんと[PERSON_002]が[EMAIL_001]で連絡。"
TOKS = {"[PERSON_001]", "[PERSON_002]", "[EMAIL_001]"}


def test_repair_variants_to_input_tokens():
    out = "【PERSON_001】 and [PERSON_2] contacted via EMAIL_001."
    assert repair_tokens(out, TOKS) == "[PERSON_001] and [PERSON_002] contacted via [EMAIL_001]."


def test_repair_never_invents():
    assert repair_tokens("[PERSON_9] and ISO 9001", TOKS) == "[PERSON_9] and ISO 9001"


def test_report():
    r = token_report(IN, "[PERSON_001] and [PERSON_003] via 【EMAIL_001】")
    assert r["input_unique"] == 3 and r["preserved_unique"] == 1
    assert r["missing"] == ["[EMAIL_001]", "[PERSON_002]"]
    assert r["invented"] == ["[PERSON_003]"]
    assert r["malformed"] == ["【EMAIL_001】"]
