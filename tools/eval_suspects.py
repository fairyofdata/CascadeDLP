"""C7 측정: 라우터의 의심 항목 확인(needs_confirmation)이 낯선 용어를 놓치지 않는가, 쓸데없이 멈추지 않는가.

  python tools/eval_suspects.py data/eval/c2_dev_tessellane qwen3.5:9b

- 헛멈춤: 용어집이 정답 10항목으로 다 채워진 상태에서 문서 5개를 라우팅 → 보류된 문서 수, 의심으로 뜬 말
- 놓침: 정답 항목을 하나씩 용어집에서 빼고(leave-one-out), 그 항목이 나오는 문서를 라우팅
        → 그 문서가 보류되고, 빠진 항목의 표기가 대기 목록에 오르는가
LLM 호출은 용어집과 무관하므로 캐시해서 같은 조각을 다시 부르지 않는다.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp import llm, router  # noqa: E402
from cascadedlp.bootstrap import key  # noqa: E402
from cascadedlp.confirm import parse_pending  # noqa: E402
from cascadedlp.gate import Gate, GateConfig  # noqa: E402
from cascadedlp.glossary import surface_pattern  # noqa: E402

_chat, _detect, _cache = llm._chat, llm.detect, {}


def cached(fn, *args):
    k = (fn.__name__, json.dumps(args, ensure_ascii=False, sort_keys=True, default=str))
    if k not in _cache:
        _cache[k] = fn(*args)
    return _cache[k]


llm._chat = lambda model, system, user, schema: cached(_chat, model, system, user, schema)
llm.detect = lambda text, model: cached(_detect, text, model)


def run(gold, docs, model, drop=None):
    """drop: 용어집에서 뺄 항목 id. → {문서: (경로, 대기 목록에 오른 표기들)}"""
    out = {}
    with tempfile.TemporaryDirectory() as home:
        home = Path(home)
        entries = [{"id": e["id"], "kind": e["kind"], "level": 2, "status": "confirmed", "surfaces": e["surfaces"],
                    "alias": e.get("alias", "")} for e in gold["entries"] if e["id"] != drop]
        (home / "projects" / "p").mkdir(parents=True)
        (home / "projects" / "p" / "glossary.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
        g = Gate(GateConfig(home=home, model=model, link=False))
        for name, text in docs.items():
            pend = home / "projects" / "p" / "pending.md"
            pend.unlink(missing_ok=True)
            r = router.route_text(g, text, "p")
            flagged = [it["title"] for it in parse_pending(pend.read_text(encoding="utf-8"))] if pend.exists() else []
            out[name] = (r.route, flagged, r.text)
    return out


def main(folder, model):
    folder = Path(folder)
    gold = json.loads((folder / "gold.json").read_text(encoding="utf-8"))
    docs = {p.name: p.read_text(encoding="utf-8") for p in sorted((folder / "docs").glob("*.md"))}

    full = run(gold, docs, model)
    false_stops = {n: f for n, (route, f, _) in full.items() if route == "needs_confirmation"}

    # 기준: 용어집에서 뺀 용어가 '가려지지 않은 채 밖으로 나갔는가'
    #   held    문서가 보류됨(무엇으로든) → 안 나감.  그중 flagged = 바로 그 용어(또는 그것을 포함한 말)가 대기 목록에 오름
    #   masked  보류는 안 됐지만 개인정보 층이 가림(조직명 등) → 안 나감
    #   leaked  그대로 나감
    cases = held = flagged_n = masked_n = 0
    leaks = []
    for e in gold["entries"]:
        pats = [re.compile(surface_pattern(s), re.IGNORECASE) for s in e["surfaces"]]
        related = {n: t for n, t in docs.items() if any(p.search(t) for p in pats)}
        res = run(gold, related, model, drop=e["id"])
        keys = {key(s) for s in e["surfaces"]}
        for n, (route, flagged, sent) in res.items():
            cases += 1
            if route != "cloud_raw" and route != "cloud_masked":
                held += 1
                flagged_n += any(any(k in key(f) for k in keys) for f in flagged)
            elif not any(p.search(sent) for p in pats):
                masked_n += 1
            else:
                leaks.append({"entry": e["id"], "doc": n, "route": route})

    result = {"corpus": folder.name, "model": model, "pipeline_version": llm.PROMPT_VERSION,
              "full_glossary_routes": {n: r for n, (r, _, _) in full.items()},
              "false_stops": false_stops, "cases": cases, "held": held, "held_with_that_term_flagged": flagged_n,
              "masked_by_pii_layer": masked_n, "leaked": len(leaks), "leaks": leaks}
    Path("results", f"c7_suspects_{folder.name}_{model.replace(':', '-')}_{llm.PROMPT_VERSION}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"용어집이 다 찼을 때 헛멈춤: {len(false_stops)}/{len(docs)}개 문서  {false_stops}")
    print(f"용어집에서 뺀 용어 {cases}건: 보류 {held} (그 용어가 대기 목록에 오름 {flagged_n}) · "
          f"개인정보 층이 가림 {masked_n} · 그대로 나감 {len(leaks)}")
    for m in leaks:
        print("  유출:", m)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
