"""P5 측정: 가명화된 합성 문장을 로컬 LLM으로 번역·요약했을 때 토큰이 살아남는가.

입력은 '정답 스팬'으로 가명화한다(탐지 오류와 분리). 번역은 문장마다 원문 언어가 아닌 두 언어로,
요약은 10문장씩 묶은 문서를 ko/ja/en 세 언어로.
  python tools/p5_eval.py --model qwen3.5:9b
"""
import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from piigate.pseudo import TOKEN_RE, PseudoMap, mask  # noqa: E402
from piigate.spans import Span  # noqa: E402
from piigate.transform import P5_PROMPT_VERSION, repair_tokens, summarize, token_report, translate  # noqa: E402


def masked_rows(paths, tmp_map):
    pmap = PseudoMap(tmp_map)  # 평가용 임시 맵 (entity_id가 같으면 같은 토큰이 되도록 링크)
    out = []
    for p in paths:
        for r in (json.loads(l) for l in open(p, encoding="utf-8")):
            spans = [Span(s["start"], s["end"], s["type"], "gold") for s in r["spans"]]
            links = {}
            for s in r["spans"]:
                if s.get("entity_id"):
                    key = f'{Path(p).stem}:{s["entity_id"]}'
                    links[r["text"][s["start"]:s["end"]]] = [x for x in pmap_alias.setdefault(key, [])]
                    pmap_alias[key].append(r["text"][s["start"]:s["end"]])
            m, _ = mask(r["text"], spans, pmap, links)
            out.append({"id": f'{Path(p).stem}:{r["id"]}', "lang": r["lang"], "masked": m})
    return out


pmap_alias: dict[str, list[str]] = {}


def targets(lang: str) -> list[str]:
    primary = lang.split("+")[0]
    return [t for t in ("ko", "ja", "en") if t != primary][:2]


def score(items):
    tot = {"input_unique": 0, "preserved_unique": 0, "invented": 0, "malformed": 0, "outputs": len(items), "all_ok": 0}
    for it in items:
        r = it["report"]
        tot["input_unique"] += r["input_unique"]
        tot["preserved_unique"] += r["preserved_unique"]
        tot["invented"] += len(r["invented"])
        tot["malformed"] += len(r["malformed"])
        tot["all_ok"] += (not r["missing"] and not r["invented"] and not r["malformed"])
    tot["preservation"] = round(tot["preserved_unique"] / tot["input_unique"], 3) if tot["input_unique"] else None
    tot["all_ok_rate"] = round(tot["all_ok"] / tot["outputs"], 3) if tot["outputs"] else None
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--eval", nargs="+", default=["data/eval/eval_v1.jsonl", "data/eval/eval_v2.jsonl"])
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    tmp_map = Path(a.out) / "_p5_tmp.map.json"
    tmp_map.unlink(missing_ok=True)
    rows = [r for r in masked_rows(a.eval, tmp_map) if TOKEN_RE.search(r["masked"])]
    tmp_map.unlink(missing_ok=True)

    trans, t_lat = [], []
    for i, r in enumerate(rows):
        for tgt in targets(r["lang"]):
            t0 = time.perf_counter()
            out = translate(r["masked"], tgt, a.model)
            t_lat.append(time.perf_counter() - t0)
            toks = {m.group(0) for m in TOKEN_RE.finditer(r["masked"])}
            fixed = repair_tokens(out, toks)
            trans.append({"id": r["id"], "target": tgt, "input": r["masked"], "output": out,
                          "report": token_report(r["masked"], out), "report_repaired": token_report(r["masked"], fixed)})
        if (i + 1) % 20 == 0:
            print(f"translate {i + 1}/{len(rows)}", file=sys.stderr)

    summ, s_lat = [], []
    for k in range(0, len(rows), 10):
        doc = "\n".join(r["masked"] for r in rows[k:k + 10])
        toks = {m.group(0) for m in TOKEN_RE.finditer(doc)}
        for lang in ("ko", "ja", "en"):
            t0 = time.perf_counter()
            out = summarize(doc, lang, a.model)
            s_lat.append(time.perf_counter() - t0)
            summ.append({"doc": k // 10, "lang": lang, "input": doc, "output": out,
                         "report": token_report(doc, out), "report_repaired": token_report(doc, repair_tokens(out, toks))})
        print(f"summarize {k // 10 + 1}/{(len(rows) + 9) // 10}", file=sys.stderr)

    def both(items):
        return {"raw": score(items), "repaired": score([{**x, "report": x["report_repaired"]} for x in items])}

    res = {"date": datetime.date.today().isoformat(), "model": a.model, "p5_prompt_version": P5_PROMPT_VERSION,
           "eval": a.eval, "translate": both(trans), "summarize": both(summ),
           "latency_s": {"translate_median": round(sorted(t_lat)[len(t_lat) // 2], 2),
                         "summarize_median": round(sorted(s_lat)[len(s_lat) // 2], 2)},
           "translate_items": trans, "summarize_items": summ}
    tag = f"{res['date']}_p5_{a.model.replace(':', '-')}_{P5_PROMPT_VERSION}"
    Path(a.out, tag + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for name in ("translate", "summarize"):
        for kind in ("raw", "repaired"):
            s = res[name][kind]
            print(f"{name:9s} {kind:8s} 보존율 {s['preservation']}  완전무결 {s['all_ok']}/{s['outputs']} "
                  f"지어냄 {s['invented']}  변형 {s['malformed']}")
    print(res["latency_s"])


if __name__ == "__main__":
    main()
