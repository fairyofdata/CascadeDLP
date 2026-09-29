"""Gate 레이어의 경계 원칙 검사 (LLM 없이 규칙만)."""
import json
from pathlib import Path

import pytest

from piigate.gate import Gate, GateConfig, PathNotAllowed, chunks

DOC = "担当: a.b@example.com / 010-2847-3916\n문의는 https://example.jp/p?id=1 로.\n"


@pytest.fixture(autouse=True)
def fake_user_home(tmp_path_factory, monkeypatch):
    """pytest 임시 폴더는 실제 AppData 아래라 차단 목록에 걸린다 → 사용자 폴더를 가짜로 바꾼다."""
    fake = tmp_path_factory.mktemp("userhome")
    monkeypatch.setenv("USERPROFILE", str(fake))
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def setup(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "doc.txt").write_text(DOC, encoding="utf-8")
    (tmp_path / "secret.txt").write_text(DOC, encoding="utf-8")
    cfg = GateConfig(home=tmp_path / "home", model=None, allowed_roots=[str(allowed)])
    return tmp_path, allowed, cfg


def test_restricted_gate_refuses_outside_paths(setup):
    tmp, allowed, cfg = setup
    g = Gate(cfg, restrict_paths=True)
    with pytest.raises(PathNotAllowed):
        g.mask_file(tmp / "secret.txt")
    with pytest.raises(PathNotAllowed):  # ..로 빠져나가기도 막힘
        g.mask_file(allowed / ".." / "secret.txt")
    r = g.mask_file(allowed / "doc.txt")
    assert "example.com" not in r.masked_text and "2847" not in r.masked_text
    with pytest.raises(PathNotAllowed):
        g.unmask_to_file(r.masked_text, r.job_id, tmp / "out.txt")


def test_empty_allowed_roots_blocks_everything(setup):
    tmp, allowed, cfg = setup
    cfg.allowed_roots = []
    with pytest.raises(PathNotAllowed):
        Gate(cfg, restrict_paths=True).mask_file(allowed / "doc.txt")


def test_unmask_to_file_returns_no_content_and_never_overwrites(setup):
    tmp, allowed, cfg = setup
    g = Gate(cfg, restrict_paths=True)
    r = g.mask_file(allowed / "doc.txt")
    answer = "요약: " + r.masked_text
    info = g.unmask_to_file(answer, r.job_id, allowed / "answer.txt")
    assert "example.com" not in json.dumps(info, ensure_ascii=False)   # 반환값에 원래 값 없음
    assert (allowed / "answer.txt").read_text(encoding="utf-8") == "요약: " + DOC
    assert info["unresolved"] == 0
    with pytest.raises(FileExistsError):
        g.unmask_to_file(answer, r.job_id, allowed / "answer.txt")


def test_same_token_across_documents_and_sessions(setup):
    """다른 문서·다른 Gate 인스턴스(=다음 주의 다른 대화)에서도 같은 값은 같은 토큰."""
    tmp, allowed, cfg = setup
    a = Gate(cfg).mask_text("메일 a.b@example.com").masked_text
    b = Gate(GateConfig(home=cfg.home, model=None)).mask_text("다시 a.b@example.com 로").masked_text
    assert a == "메일 [EMAIL_001]" and b == "다시 [EMAIL_001] 로"


def test_counts_have_types_only(setup):
    tmp, allowed, cfg = setup
    r = Gate(cfg).mask_text(DOC)
    assert r.counts == {"EMAIL": 1, "PHONE": 1, "URL": 1}


def test_bad_job_id_rejected(setup):
    tmp, allowed, cfg = setup
    with pytest.raises(ValueError):
        Gate(cfg).unmask_text("x", "../../etc")


def test_config_default_is_user_folder(tmp_path):
    cfg = GateConfig.load(tmp_path / "h")
    assert cfg.allowed_roots == [str(Path.home())] and (tmp_path / "h" / "config.json").exists()


def test_denied_folders_even_inside_allowed(tmp_path):
    """허용 범위가 넓어도 가명 맵 폴더·.ssh·.claude 는 항상 막힌다."""
    home = tmp_path / "piigate_home"
    cfg = GateConfig(home=home, model=None, allowed_roots=[str(tmp_path), str(Path.home())])
    g = Gate(cfg, restrict_paths=True)
    for p in (home / "default.map.json", Path.home() / ".ssh" / "id_rsa", Path.home() / ".claude" / "x.jsonl"):
        with pytest.raises(PathNotAllowed):
            g.mask_file(p)


@pytest.mark.parametrize("name,content", [
    ("note.md", "# 회의\n- 담당: a.b@example.com\n- 연락: 010-2847-3916\n"),
    ("data.json", '{"name": "x", "email": "a.b@example.com", "tel": "090-3712-5584"}'),
])
def test_md_and_json_files(setup, name, content):
    """md·json도 그대로 처리. json은 가명화 뒤에도 유효한 json이어야 한다."""
    tmp, allowed, cfg = setup
    (allowed / name).write_text(content, encoding="utf-8")
    g = Gate(cfg, restrict_paths=True)
    r = g.mask_file(allowed / name)
    assert "example.com" not in r.masked_text
    if name.endswith(".json"):
        json.loads(r.masked_text)
    g.unmask_to_file(r.masked_text, r.job_id, allowed / ("back_" + name))
    assert (allowed / ("back_" + name)).read_text(encoding="utf-8") == content


def test_chunks_cover_text_exactly():
    text = ("가나다라마바사。" * 300 + "\n") * 3 + "short\n" + "x" * 4000
    parts = chunks(text, 1500)
    assert "".join(c for _, c in parts) == text
    assert all(len(c) <= 1500 for _, c in parts)
    assert all(text[o:o + len(c)] == c for o, c in parts)
