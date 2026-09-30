"""C2 측정: 용어집 부트스트랩 후보를 정답 용어집과 비교.

  python tools/eval_bootstrap.py data/eval/c2_dev_tessellane qwen3.5:9b

- 항목 재현율: 정답 항목 중 후보(표기 줄)에 하나라도 오른 비율
- 표기 재현율: 정답 표기 중 후보 표기 줄에 오른 비율 (+ '확인 필요' 포함 시)
- 후보 정밀도: 후보 묶음 중 정답 항목에 해당하는 비율 (잡음이 많으면 검토 시간↑)
- 잘못 합침: 한 후보 묶음의 표기 줄에 정답 항목이 둘 이상 섞인 경우
- 확인 필요 정확도: LLM 번역 제안 표기가 실제로 같은 항목인 비율
- 끝까지(모두 채택 가정): 문서 속 정답 용어 등장 중 가려지는 비율, 정답이 아닌데 가려지는 등장 수
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp.bootstrap import BOOTSTRAP_PROMPT_VERSION, bootstrap, key, read_docs, render_review  # noqa: E402
from cascadedlp.glossary import Entry, Glossary, surface_pattern  # noqa: E402


def main(folder, model):
    folder = Path(folder)
    gold = json.loads((folder / "gold.json").read_text(encoding="utf-8"))
    owner = {key(s): e["id"] for e in gold["entries"] for s in e["surfaces"]}
    res = bootstrap(folder / "docs", model)

    hit_entries, hit_surfaces, hit_with_sugg = set(), set(), set()
    precise = wrong_merge = 0
    sugg_total = sugg_ok = 0
    groups_per_entry: dict[str, int] = {}
    noise = []
    for g in res.groups:
        ids = {owner[key(s)] for s in g.surfaces if key(s) in owner}
        hit_entries |= ids
        hit_surfaces |= {key(s) for s in g.surfaces if key(s) in owner}
        hit_with_sugg |= {key(s) for s in list(g.surfaces) + list(g.suggested) if key(s) in owner}
        if ids:
            precise += 1
            for i in ids:
                groups_per_entry[i] = groups_per_entry.get(i, 0) + 1
        else:
            noise.append(g.title)
        if len(ids) > 1:
            wrong_merge += 1
        for s in g.suggested:
            if s in g.surfaces:
                continue
            sugg_total += 1
            sugg_ok += bool(ids) and owner.get(key(s)) in ids
    gold_keys = {key(s) for e in gold["entries"] for s in e["surfaces"]}
    excluded_gold = [g.title for g in res.excluded if any(key(s) in owner for s in g.surfaces)]
    persons = [g.title for g in res.groups if any(key(s) in {key(p) for p in gold.get("persons", [])} for s in g.surfaces)]

    # 끝까지: 후보를 전부 채택했다고 가정한 용어집으로 문서를 가렸을 때
    gl = Glossary([Entry(f"TERM_{n:02d}", "TERM", 2, list(g.surfaces), "", "confirmed")
                   for n, g in enumerate(res.groups, 1)])
    gold_pats = [re.compile(surface_pattern(s), re.IGNORECASE) for e in gold["entries"] for s in e["surfaces"]]
    occ = covered = over = 0
    for _, text in read_docs(folder / "docs"):
        masked = [(s.start, s.end) for s in gl.match(text)]
        gold_occ = []
        for p in gold_pats:
            gold_occ += [(m.start(), m.end()) for m in p.finditer(text)]
        gold_occ = sorted(set(gold_occ))
        occ += len(gold_occ)
        covered += sum(any(a <= s and e <= b for a, b in masked) for s, e in gold_occ)
        over += sum(not any(a < e2 and s2 < b for s2, e2 in gold_occ) for a, b in masked)

    n_entries = len(gold["entries"])
    result = {
        "corpus": folder.name, "model": model, "bootstrap_version": BOOTSTRAP_PROMPT_VERSION,
        "docs": res.n_docs, "llm_calls": res.llm_calls, "seconds": res.seconds,
        "candidates": len(res.groups), "excluded": len(res.excluded),
        "entry_recall": f"{len(hit_entries)}/{n_entries}",
        "surface_recall": f"{len(hit_surfaces)}/{len(gold_keys)}",
        "surface_recall_with_suggestions": f"{len(hit_with_sugg)}/{len(gold_keys)}",
        "candidate_precision": round(precise / len(res.groups), 3) if res.groups else None,
        "wrong_merges": wrong_merge,
        "fragmented_entries": sum(v > 1 for v in groups_per_entry.values()),
        "suggestions_correct": f"{sugg_ok}/{sugg_total}",
        "gold_wrongly_excluded": excluded_gold,
        "persons_in_candidates": persons,
        "accept_all_coverage": f"{covered}/{occ}",
        "accept_all_over_masked_occurrences": over,
        "noise_candidates": noise,
        "missed_entries": sorted({e["id"] for e in gold["entries"]} - hit_entries),
    }
    tag = f"c2_bootstrap_{folder.name}_{model.replace(':', '-')}_{BOOTSTRAP_PROMPT_VERSION}"
    Path("results", tag + ".json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("results", tag + ".review.md").write_text(render_review(res, gold["project"]), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
