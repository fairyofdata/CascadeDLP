"""C2 결정론 부분: 표기 키, 검토 md 파싱, apply(용어집 반영). LLM 없이."""
import json
from collections import Counter

from cascadedlp.bootstrap import BootstrapResult, Group, apply_review, key, parse_review, render_review


def test_key_merges_code_variants():
    assert key("Adaptive Scheduler") == key("adaptive_scheduler") == key("AdaptiveScheduler") == key("adaptive-scheduler")
    assert key("레저 브리지") == key("레저브리지")


def make_result():
    g1 = Group(surfaces=Counter({"조율기": 5, "Adaptive Scheduler": 4}), kinds=Counter({"COMPONENT": 2}),
               descriptions=["작업 스케줄러"], docs={"a", "b"}, sources={"llm"}, suggested={"適応スケジューラ": "번역 관계(LLM 제안)"})
    g2 = Group(surfaces=Counter({"Night Harvest": 2}), kinds=Counter({"TERM": 1}), docs={"a"}, sources={"llm"})
    return BootstrapResult([g1, g2], [Group(surfaces=Counter({"GitHub": 1}), public=True)], 2, 5, 1.0)


def test_render_then_parse_only_checked_and_not_suggestions():
    md = render_review(make_result(), "p")
    md = md.replace("## [ ] C001", "## [x] C001").replace("- level: 2", "- level: 1", 1)
    items = parse_review(md)
    assert len(items) == 1
    it = items[0]
    assert it["kind"] == "COMPONENT" and it["level"] == 1 and it["alias"] == "작업 스케줄러"
    assert it["surfaces"] == ["조율기", "Adaptive Scheduler"]          # '확인 필요' 표기는 옮기지 않으면 안 들어감


def test_suggestion_included_only_when_moved_to_surface_line():
    md = render_review(make_result(), "p").replace("## [ ] C001", "## [x] C001")
    md = md.replace("- 표기: 조율기 | Adaptive Scheduler", "- 표기: 조율기 | Adaptive Scheduler | 適応スケジューラ")
    assert parse_review(md)[0]["surfaces"][-1] == "適応スケジューラ"


def test_excluded_can_be_rescued():
    md = render_review(make_result(), "p").replace("- [ ] GitHub", "- [x] GitHub")
    assert [i["surfaces"] for i in parse_review(md)] == [["GitHub"]]


def test_apply_creates_and_extends(tmp_path):
    path = tmp_path / "glossary.json"
    md = render_review(make_result(), "p").replace("## [ ] C001", "## [x] C001").replace("## [ ] C002", "## [x] C002")
    info = apply_review(md, path, "p")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert info["added"] == 2
    ids = [e["id"] for e in data["entries"]]
    assert ids == ["COMPONENT_01", "TERM_01"] and all(e["status"] == "confirmed" for e in data["entries"])
    # 두 번째 검토에서 같은 대상의 새 표기 → 기존 항목에 표기만 더함
    md2 = "## [x] C001 · x\n- kind: COMPONENT\n- level: 2\n- 설명: \n- 표기: 조율기 | adaptive_scheduler_v2\n"
    info2 = apply_review(md2, path, "p")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert info2 == {**info2, "added": 0, "extended": 1}
    assert "adaptive_scheduler_v2" in data["entries"][0]["surfaces"]
