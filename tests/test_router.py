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


def suspect_gate(gate, monkeypatch, cands):
    """로컬 LLM이 있는 것처럼 꾸미고, 후보 추출 결과를 고정한다."""
    gate.cfg.model = "fake"
    monkeypatch.setattr(router.llm, "detect", lambda t, m: ([], 0.0))
    monkeypatch.setattr(router, "term_candidates", lambda text, model: {
        router.key(s): {"surface": s, "kind": "COMPONENT", "desc": "설명", "llm": True} for s in cands if s in text})
    return gate


def test_suspect_holds_document_then_confirm_releases(gate, monkeypatch):
    """의심 → 보류(내용·용어를 돌려주지 않음) → 사용자가 로컬에서 표시 → 다시 요청하면 통과."""
    from cascadedlp.confirm import apply_pending, project_dir
    g = suspect_gate(gate, monkeypatch, ["Dock Pulse", "Kubernetes", "조율기"])
    text = "조율기는 Dock Pulse 상태를 읽고 Kubernetes에 배포된다."
    r = router.route_text(g, text, "tsl")
    assert r.route == "needs_confirmation" and r.text == "" and r.n_suspects == 2      # 조율기는 용어집에 있음
    assert "Dock Pulse" not in r.notice and "Kubernetes" not in " ".join(r.reasons)     # 용어는 호출자에게 안 감
    pdir = project_dir(g.cfg.home, "tsl")
    md = (pdir / "pending.md").read_text(encoding="utf-8")
    assert "Dock Pulse" in md and "Kubernetes" in md and "조율기" not in md.split("끝나면")[1]
    # 사용자가 표시: Dock Pulse 보호, Kubernetes 일반어
    md = md.replace("## [ ] P001 · Dock Pulse", "## [x] P001 · Dock Pulse").replace("## [ ] P002 · Kubernetes", "## [o] P002 · Kubernetes")
    (pdir / "pending.md").write_text(md, encoding="utf-8")
    assert apply_pending(pdir, "tsl") == {"protected": 1, "allowed": 1, "left": 0}
    r = router.route_text(g, text, "tsl")
    assert r.route == "cloud_masked" and "Dock Pulse" not in r.text and "Kubernetes" in r.text
    assert "Dock Pulse" not in audit_lines(g) and "Kubernetes" not in audit_lines(g)


def test_undecided_suspect_keeps_holding_and_is_not_duplicated(gate, monkeypatch):
    from cascadedlp.confirm import apply_pending, parse_pending, project_dir
    g = suspect_gate(gate, monkeypatch, ["Dock Pulse"])
    router.route_text(g, "Dock Pulse 점검", "tsl")
    router.route_text(g, "Dock Pulse 재점검", "tsl")
    pdir = project_dir(g.cfg.home, "tsl")
    assert len(parse_pending((pdir / "pending.md").read_text(encoding="utf-8"))) == 1
    assert apply_pending(pdir, "tsl")["left"] == 1
    assert router.route_text(g, "Dock Pulse 점검", "tsl").route == "needs_confirmation"


def test_no_project_means_no_suspect_check(gate, monkeypatch):
    g = suspect_gate(gate, monkeypatch, ["Dock Pulse"])
    assert router.route_text(g, "Dock Pulse 점검").route == "cloud_raw"


def test_too_many_suspects_blocks(gate, monkeypatch):
    names = [f"Module Alpha{chr(97 + i)}" for i in range(6)]
    g = suspect_gate(gate, monkeypatch, names)
    g.cfg.max_suspects = 5
    r = router.route_text(g, " ".join(names), "tsl")
    assert r.route == "block" and "bootstrap" in r.notice


def test_block_when_mostly_masked_or_token_like(gate):
    long_text = ("조율기 " * 90) + "끝."            # 300자 이상이고 대부분이 가릴 대상
    r = router.route_text(gate, long_text, "tsl")
    assert r.route == "block" and "비율" in r.reasons[0]
    r = router.route_text(gate, "표 참고: [ITEM_01] 값", "tsl")
    assert r.route == "block" and "모양" in r.reasons[0]


def test_restricted_route_file_refuses_outside(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "u"))
    monkeypatch.setenv("HOME", str(tmp_path / "u"))
    g = Gate(GateConfig(home=tmp_path / "home", model=None, allowed_roots=[str(tmp_path / "allowed")]), restrict_paths=True)
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    from cascadedlp.gate import PathNotAllowed
    with pytest.raises(PathNotAllowed):
        router.route_file(g, tmp_path / "secret.md")
