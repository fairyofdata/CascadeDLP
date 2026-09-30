"""C5 라우터: 경로 결정, 로컬 답은 파일로만, 감사 로그에 내용 없음. (LLM 없이)"""
import json
from pathlib import Path

import pytest

from cascadedlp import router
from cascadedlp.gate import Gate, GateConfig

GLOSSARY = {"project": "tsl", "entries": [
    {"id": "COMPONENT_01", "kind": "COMPONENT", "level": 2, "status": "confirmed", "surfaces": ["조율기"], "alias": ""},
    {"id": "ALGORITHM_01", "kind": "ALGORITHM", "level": 3, "status": "confirmed", "surfaces": ["Braid Solver"], "alias": ""},
]}
KEY = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWx0123456789"


@pytest.fixture
def gate(tmp_path):
    home = tmp_path / "home"
    (home / "projects" / "tsl").mkdir(parents=True)
    (home / "projects" / "tsl" / "glossary.json").write_text(json.dumps(GLOSSARY, ensure_ascii=False), encoding="utf-8")
    return Gate(GateConfig(home=home, model=None))


def audit_lines(g):
    return (g.cfg.home / "audit.jsonl").read_text(encoding="utf-8")


def test_cloud_raw(gate):
    r = router.route_text(gate, "회의는 목요일에 합니다.", "tsl")
    assert r.route == "cloud_raw" and r.text == "회의는 목요일에 합니다."


def test_cloud_masked(gate):
    r = router.route_text(gate, "조율기 담당: a.b@example.com", "tsl")
    assert r.route == "cloud_masked" and r.text == "[COMPONENT_01] 담당: [EMAIL_001]" and r.job_id


def test_local_only_writes_file_and_returns_no_text(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(router, "local_answer", lambda model, text, q: "로컬 답: 경로 계산 방식 설명")
    gate.cfg.model = "fake"
    monkeypatch.setattr(router.llm, "detect", lambda t, m: ([], 0.0))
    out = tmp_path / "ans.md"
    r = router.route_text(gate, "Braid Solver는 경로를 이렇게 계산한다.", "tsl", question="요약해줘", local_out=out)
    assert r.route == "local_only" and r.text == "" and r.local_answer_path == str(out.resolve())
    assert out.read_text(encoding="utf-8").startswith("로컬 답")
    with pytest.raises(FileExistsError):   # 덮어쓰기 금지
        router.route_text(gate, "Braid Solver 다시", "tsl", question="q", local_out=out)


def test_local_only_without_question_just_decides(gate):
    r = router.route_text(gate, "Braid Solver 설명", "tsl")
    assert r.route == "local_only" and not r.local_answer_path and "ALGORITHM_01" in r.notice


def test_secret_block_and_mask_policy(gate):
    r = router.route_text(gate, f"key={KEY}", "tsl")
    assert r.route == "block" and r.text == ""
    gate.cfg.secret_policy = "mask"
    r = router.route_text(gate, f"key={KEY}", "tsl")
    assert r.route == "cloud_masked" and KEY not in r.text and "[SECRET_001]" in r.text


def test_audit_has_no_content(gate, tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("조율기 담당: a.b@example.com / Braid Solver 없음", encoding="utf-8")
    router.route_text(gate, "조율기 담당: a.b@example.com", "tsl")
    router.route_file(gate, f, "tsl")
    router.route_text(gate, f"key={KEY}", "tsl")
    log = audit_lines(gate)
    for secret in ("조율기", "a.b@example.com", "Braid", KEY, "doc.md", str(tmp_path)):
        assert secret not in log
    routes = [json.loads(line)["route"] for line in log.splitlines()]
    assert routes == ["cloud_masked", "local_only", "block"]


def test_restricted_route_file_refuses_outside(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "u"))
    monkeypatch.setenv("HOME", str(tmp_path / "u"))
    g = Gate(GateConfig(home=tmp_path / "home", model=None, allowed_roots=[str(tmp_path / "allowed")]), restrict_paths=True)
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    from cascadedlp.gate import PathNotAllowed
    with pytest.raises(PathNotAllowed):
        router.route_file(g, tmp_path / "secret.md")
