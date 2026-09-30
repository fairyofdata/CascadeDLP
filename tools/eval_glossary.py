"""C1 측정: 프로젝트 용어집 매칭 + 레벨별 출력 (LLM 없이, 결정론).

  python tools/eval_glossary.py data/eval/c1_tessellane              # 규칙 + 용어집
  python tools/eval_glossary.py data/eval/c1_tessellane qwen3.5:9b   # + 로컬 LLM

1) 매칭: 용어집이 정답 용어 스팬(kind + 용어집 id)을 정확히 찾는가 — P/R/F1, 오류 목록
2) Gate(규칙만 + 용어집) 문장별 결과:
   - L3 용어가 있는 문장은 거부(blocked)되는가
   - L1·L2 용어의 원래 표기가 가린 텍스트에 남지 않는가(유출 0)
   - L0 용어는 그대로 남는가
   - 복원이 원문과 바이트 일치하는가
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp.gate import Gate, GateConfig  # noqa: E402
from cascadedlp.glossary import Glossary  # noqa: E402
from cascadedlp.llm import PROMPT_VERSION  # noqa: E402

GLOSSARY_KINDS = {"PROJECT", "COMPONENT", "ALGORITHM", "TERM"}


def main(folder, model=None):
    folder = Path(folder)
    gl = Glossary.load(folder / "glossary.json")
    rows = [json.loads(l) for l in open(folder / "docs_v1.jsonl", encoding="utf-8")]
    by_id = {e.id: e for e in gl.entries}
    is_term = lambda s: s.get("entity_id") in by_id  # noqa: E731  (ORG_01 같은 용어집 항목 포함)

    tp = fp = fn = 0
    errors = []
    for r in rows:
        gold = {(s["start"], s["end"], s["entity_id"]) for s in r["spans"] if is_term(s)}
        got = {(s.start, s.end, s.entity_id) for s in gl.match(r["text"])}
        tp += len(gold & got)
        fp += len(got - gold)
        fn += len(gold - got)
        errors += [{"id": r["id"], "kind": "miss", "text": r["text"][a:b], "entry": e} for a, b, e in gold - got]
        errors += [{"id": r["id"], "kind": "extra", "text": r["text"][a:b], "entry": e} for a, b, e in got - gold]
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * rc / (p + rc) if p + rc else 0.0

    with tempfile.TemporaryDirectory() as home:
        home = Path(home)
        (home / "projects" / "tessellane").mkdir(parents=True)
        (home / "projects" / "tessellane" / "glossary.json").write_text(
            (folder / "glossary.json").read_text(encoding="utf-8"), encoding="utf-8")
        g = Gate(GateConfig(home=home, model=model, link=False))
        stats = {"sentences": len(rows), "blocked": 0, "blocked_expected": 0, "leaks_glossary": 0, "leaks_other": 0,
                 "over_masked": 0, "l0_kept": 0,
                 "l0_total": 0, "roundtrip_ok": 0, "roundtrip_total": 0}
        examples = []
        for r in rows:
            levels = {by_id[s["entity_id"]].effective_level for s in r["spans"] if is_term(s)}
            res = g.mask_text(r["text"], "tessellane")
            stats["blocked_expected"] += 3 in levels
            if res.blocked:
                stats["blocked"] += 1
                continue
            for s in r["spans"]:
                surface = r["text"][s["start"]:s["end"]]
                lvl = by_id[s["entity_id"]].effective_level if is_term(s) else 2
                if lvl == 0:
                    stats["l0_total"] += 1
                    stats["l0_kept"] += surface in res.masked_text
                elif surface in res.masked_text:
                    key = "leaks_glossary" if is_term(s) else "leaks_other"  # other = 개인정보 등(규칙만이면 이름은 못 잡음)
                    stats[key] = stats.get(key, 0) + 1
                    errors.append({"id": r["id"], "kind": key, "text": surface})
            # 과잉 가림(정보 손실): 정답에 없는 것을 가렸나 (예: LLM이 일반명사·공개 라이브러리를 ORG로 잡음)
            gold_surfaces = [r["text"][s["start"]:s["end"]] for s in r["spans"]
                             if not (is_term(s) and by_id[s["entity_id"]].effective_level == 0)]
            for x in g._restore_table(res.job_id):
                if x["surface"] in gold_surfaces:
                    gold_surfaces.remove(x["surface"])
                else:
                    stats["over_masked"] = stats.get("over_masked", 0) + 1
                    errors.append({"id": r["id"], "kind": "over_masked", "text": x["surface"]})
            stats["roundtrip_total"] += 1
            stats["roundtrip_ok"] += g.unmask_text(res.masked_text, res.job_id) == r["text"]
            if len(examples) < 8:
                examples.append({"id": r["id"], "masked": res.masked_text})

    result = {"pipeline_version": PROMPT_VERSION, "model": model, "glossary": str(folder / "glossary.json"),
              "match": {"tp": tp, "fp": fp, "fn": fn, "P": round(p, 3), "R": round(rc, 3), "F1": round(f, 3)},
              "gate": stats, "errors": errors, "examples": examples}
    tag = (model or "rules").replace(":", "-")
    out = Path("results") / f"c1_glossary_{folder.name}_{tag}_{PROMPT_VERSION}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("match", "gate")}, ensure_ascii=False, indent=1))
    for e in errors:
        print("  ", e)
    for x in examples:
        print(f"  {x['id']}: {x['masked']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)   # 두 번째 인자: 로컬 LLM 모델 (생략하면 규칙만)
