"""C1 프로젝트 용어집: 표기 변형 매칭, 레벨별 처리, 복원, 프로젝트 해석, 비밀키 규칙. (LLM 없이)"""
import json
from pathlib import Path

import pytest

from cascadedlp.gate import Gate, GateConfig
from cascadedlp.glossary import Entry, Glossary
from cascadedlp.rules import detect
from cascadedlp.transform import repair_tokens

ENTRIES = [
    Entry("COMPONENT_01", "COMPONENT", 1, ["Adaptive Scheduler", "조율기"], "작업 우선순위 스케줄러", "confirmed"),
    Entry("ALGORITHM_01", "ALGORITHM", 3, ["Braid Solver"], "경로 최적화", "confirmed"),
    Entry("ALGORITHM_02", "ALGORITHM", 2, ["Ripple Rank"], "점수 산식", "confirmed"),
    Entry("TERM_01", "TERM", 1, ["Night Harvest"], "야간 수집", "proposed"),
    Entry("PROJECT_01", "PROJECT", 1, ["Tessellane", "TSL"], "물류 플랫폼", "confirmed"),
    Entry("PROJECT_02", "PROJECT", 0, ["FastAPI"], "", "confirmed"),
]


def found(gl, text):
    return [(text[s.start:s.end], s.entity_id) for s in gl.match(text)]


@pytest.mark.parametrize("text", ["Adaptive Scheduler", "adaptive_scheduler", "AdaptiveScheduler",
                                  "adaptive-scheduler", "ADAPTIVE SCHEDULER"])
def test_surface_variants(text):
    assert found(Glossary(ENTRIES), f"run {text} now") == [(text, "COMPONENT_01")]


@pytest.mark.parametrize("text", ["an adaptive scheduling paper", "Atlassian TSLA", "Tessellation", "ripple ranking"])
def test_no_partial_word_matches(text):
    assert found(Glossary(ENTRIES), text) == []


def test_levels_and_render():
    gl = Glossary(ENTRIES)
    by = {e.id: e for e in gl.entries}
    assert by["COMPONENT_01"].render() == "[COMPONENT_01: 작업 우선순위 스케줄러]"
    assert by["ALGORITHM_02"].render() == "[ALGORITHM_02]"
    assert by["TERM_01"].effective_level == 2 and by["TERM_01"].render() == "[TERM_01]"  # 미확정 → 보수적으로 L2


def test_validation_problems():
    gl = Glossary([Entry("bad", "WHAT", 5, ["x"], ""), Entry("TERM_09", "TERM", 1, ["x"], "", "confirmed")])
    joined = " ".join(gl.problems)
    assert "id는" in joined and "kind" in joined and "level" in joined and "alias" in joined and "중복" in joined


@pytest.fixture
def gate(tmp_path):
    home = tmp_path / "home"
    (home / "projects" / "tsl").mkdir(parents=True)
    data = {"project": "tsl", "entries": [e.__dict__ for e in ENTRIES]}
    (home / "projects" / "tsl" / "glossary.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    return Gate(GateConfig(home=home, model=None, projects={"tsl": [str(work)]})), work


def test_gate_levels(gate):
    g, _ = gate
    text = "Tessellane의 조율기는 Ripple Rank와 Night Harvest를 쓰고 FastAPI 위에서 돈다."
    r = g.mask_text(text, "tsl")
    assert r.masked_text == ("[PROJECT_01: 물류 플랫폼]의 [COMPONENT_01: 작업 우선순위 스케줄러]는 [ALGORITHM_02]와 "
                             "[TERM_01]를 쓰고 FastAPI 위에서 돈다.")
    assert g.unmask_text(r.masked_text, r.job_id) == text


def test_gate_blocks_l3_without_revealing_term(gate):
    g, _ = gate
    r = g.mask_text("Braid Solver 수식 설명", "tsl")
    assert r.blocked and r.masked_text == "" and "Braid" not in r.notice and "ALGORITHM_01" in r.notice


def test_l2_context_drop_removes_sentences_keeps_lines(gate):
    g, _ = gate
    text = "# 설계\n- Ripple Rank는 가중합으로 점수를 낸다. 조율기는 큐를 본다.\n- FastAPI 사용.\n"
    r = g.mask_text(text, "tsl", l2_context="drop")
    assert r.masked_text == "# 설계\n- [COMPONENT_01: 작업 우선순위 스케줄러]는 큐를 본다.\n- FastAPI 사용.\n"


def test_l2_context_generalize_falls_back_to_drop_when_token_lost(gate, monkeypatch):
    from cascadedlp import llm
    g, _ = gate
    monkeypatch.setattr(llm, "generalize", lambda s, m: "점수를 내는 부품이다.")   # 토큰을 잃은 출력 → 안전하게 제거
    g.cfg.model = "fake"
    monkeypatch.setattr(llm, "detect", lambda text, model: ([], 0.0))
    r = g.mask_text("Ripple Rank는 가중합으로 점수를 낸다.\n", "tsl", l2_context="generalize")
    assert r.masked_text == "\n"
    monkeypatch.setattr(llm, "generalize", lambda s, m: "[ALGORITHM_02]는 점수를 내는 부품이다.")
    r = g.mask_text("Ripple Rank는 가중합으로 점수를 낸다.\n", "tsl", l2_context="generalize")
    assert r.masked_text == "[ALGORITHM_02]는 점수를 내는 부품이다.\n"


def test_restore_by_id_even_if_description_changed(gate):
    """외부 LLM이 설명 부분을 바꾸거나 지워도 id로 복원된다."""
    g, _ = gate
    r = g.mask_text("조율기 개선", "tsl")
    answer = "[COMPONENT_01: 스케줄러 모듈]과 [COMPONENT_01]을 분리하세요."
    assert g.unmask_text(answer, r.job_id) == "조율기과 조율기을 분리하세요."


def test_project_from_folder_mapping(gate):
    g, work = gate
    f = work / "design.md"
    f.write_text("Adaptive Scheduler 설계", encoding="utf-8")
    assert g.mask_file(f).masked_text.startswith("[COMPONENT_01:")
    assert g.mask_file(f, "tsl").project == "tsl"
    with pytest.raises(ValueError):
        g.project_for(project="../evil")
    with pytest.raises(FileNotFoundError):
        g.glossary("nope")


def test_no_glossary_means_pii_only(gate):
    g, _ = gate
    r = g.mask_text("조율기 담당 a@example.com")
    assert r.masked_text == "조율기 담당 [EMAIL_001]"


@pytest.mark.parametrize("secret", [
    "sk-proj-AbCdEfGhIjKlMnOpQrStUvWx0123456789",
    "ghp_" + "a1B2" * 9,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "-----BEGIN PRIVATE KEY-----\nMIIEv\n-----END PRIVATE KEY-----",
])
def test_secret_rules(secret):
    text = f"key = {secret}\n"
    spans = [s for s in detect(text) if s.type == "SECRET"]
    assert len(spans) == 1 and text[spans[0].start:spans[0].end] == secret


def test_repair_keeps_description_tokens():
    toks = {"[COMPONENT_01]"}
    assert repair_tokens("[COMPONENT_01: 스케줄러] and COMPONENT_1", toks) == "[COMPONENT_01: 스케줄러] and [COMPONENT_01]"
