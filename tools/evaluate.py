"""평가: 유형별 precision/recall/F1 (완전 일치·겹침 일치) + 교차 표기 연결 + 지연시간.

  python tools/evaluate.py                       # 규칙만 (P2)
  python tools/evaluate.py --llm qwen3:8b        # 규칙 + LLM (P4)

결과는 results/<날짜>_<모드>.json/.md 로 저장된다(집계 수치만, 원문 없음).
- 완전 일치: start·end·유형이 모두 같음
- 겹침 일치: 유형이 같고 한 글자라도 겹침 (예측 하나는 정답 하나에만 대응)
- 교차 표기 연결: 정답 PERSON 표기 전체(탐지와 분리하려고 정답 표기를 입력)를 묶게 하고,
  '정답 묶음의 모든 표기가 한 묶음에 있고, 그 묶음에 다른 사람이 섞이지 않은' 비율 + 쌍 단위 P/R.
  규칙만 모드의 연결 = 정규화 후 같은 문자열끼리만 묶기(pseudo.norm).
"""
import argparse
import datetime
import itertools
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp import linking, llm, rules  # noqa: E402
from cascadedlp.pseudo import norm  # noqa: E402
from cascadedlp.spans import resolve  # noqa: E402

TYPES = ["PERSON", "EMAIL", "PHONE", "POSTAL", "ADDRESS", "URL", "ID_NUMBER", "ORG"]


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 3), round(r, 3), round(f, 3)


def match(gold, pred, overlap: bool):
    """→ 유형별 {tp, fp, fn}"""
    c = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    used = set()
    for g in gold:
        hit = None
        for i, p in enumerate(pred):
            if i in used or p.type != g["type"]:
                continue
            if (p.start, p.end) == (g["start"], g["end"]) or (overlap and p.start < g["end"] and g["start"] < p.end):
                hit = i
                break
        if hit is None:
            c[g["type"]]["fn"] += 1
        else:
            used.add(hit)
            c[g["type"]]["tp"] += 1
    for i, p in enumerate(pred):
        if i not in used:
            c[p.type]["fp"] += 1
    return c


def table(counts):
    rows, tot = {}, {"tp": 0, "fp": 0, "fn": 0}
    for t in TYPES:
        k = counts.get(t, {"tp": 0, "fp": 0, "fn": 0})
        for x in tot:
            tot[x] += k[x]
        if sum(k.values()):
            rows[t] = {**k, **dict(zip("PRF", prf(k["tp"], k["fp"], k["fn"])))}
    rows["ALL"] = {**tot, **dict(zip("PRF", prf(tot["tp"], tot["fp"], tot["fn"])))}
    return rows


def eval_linking(rows, model, saved_romans: dict | None = None):
    """saved_romans: 이전 결과 JSON의 romanized — 주면 LLM을 부르지 않고 코드 판정만 다시 한다(tools/relink.py)."""
    surf2eid = {}
    for r in rows:
        for s in r["spans"]:
            if s["type"] == "PERSON":
                text = r["text"][s["start"]:s["end"]]
                surf2eid.setdefault(text, s.get("entity_id") or f"_single_{text}")
    surfaces = list(surf2eid)
    romans = None
    if saved_romans:
        romans = [saved_romans[s] for s in surfaces]
        groups, secs = linking.group(romans), 0.0
    elif model:
        groups, secs, romans = linking.link(surfaces, model)
    else:
        by = defaultdict(list)
        for i, s in enumerate(surfaces):
            by[norm(s)].append(i)
        groups, secs = list(by.values()), 0.0
    pred_of = {i: gi for gi, g in enumerate(groups) for i in g}
    gold_clusters = defaultdict(list)
    for i, s in enumerate(surfaces):
        gold_clusters[surf2eid[s]].append(i)
    multi = {k: v for k, v in gold_clusters.items() if len(v) > 1}
    correct = 0
    for members in multi.values():
        gids = {pred_of[i] for i in members}
        if len(gids) == 1 and set(groups[gids.pop()]) == set(members):
            correct += 1
    # 쌍 단위: 같은 사람 쌍을 같은 묶음에 넣었나
    tp = fp = fn = 0
    for i, j in itertools.combinations(range(len(surfaces)), 2):
        same_gold = surf2eid[surfaces[i]] == surf2eid[surfaces[j]]
        same_pred = pred_of[i] == pred_of[j]
        tp += same_gold and same_pred
        fp += (not same_gold) and same_pred
        fn += same_gold and not same_pred
    p, r, f = prf(tp, fp, fn)
    return {"n_surfaces": len(surfaces), "n_clusters_multi": len(multi), "cluster_exact": correct,
            "cluster_exact_rate": round(correct / len(multi), 3), "pair_P": p, "pair_R": r, "pair_F": f,
            "seconds": round(secs, 2),
            # 오류 분석용: 틀린 묶음 (합성 데이터라 표기를 그대로 남긴다)
            "wrong_clusters": [[surfaces[i] for i in g] for g in groups
                               if len({surf2eid[surfaces[i]] for i in g}) > 1],
            "split_clusters": [[surfaces[i] for i in v] for v in multi.values()
                               if len({pred_of[i] for i in v}) > 1],
            "romanized": {s: romans[i] for i, s in enumerate(surfaces)} if romans else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="data/eval/eval_v1.jsonl")
    ap.add_argument("--llm", metavar="MODEL")
    ap.add_argument("--gliner", action="store_true", help="기준선: GLiNER 스팬을 더한다")
    ap.add_argument("--no-rules", action="store_true", help="규칙 층을 끈다(기준선 단독 측정용)")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    if a.gliner:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import gliner_baseline
    rows = [json.loads(l) for l in open(a.eval, encoding="utf-8")]

    exact, over, lat, errors = defaultdict(dict), defaultdict(dict), [], []
    ex_c = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    ov_c = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for i, r in enumerate(rows):
        spans = [] if a.no_rules else rules.detect(r["text"])
        if a.llm or a.gliner:
            ls, secs = llm.detect(r["text"], a.llm) if a.llm else gliner_baseline.detect(r["text"])
            if i > 0:  # 첫 문장은 모델 로딩 시간이 섞이므로 지연 통계에서 뺀다
                lat.append(secs * 1000)
            spans += ls
        pred = resolve(spans)
        for c, acc in ((match(r["spans"], pred, False), ex_c), (match(r["spans"], pred, True), ov_c)):
            for t, k in c.items():
                for x in k:
                    acc[t][x] += k[x]
        # 오류 목록(id·유형·위치만 — 원문은 합성이지만 결과 파일엔 수치 위주로)
        gold = {(g["start"], g["end"], g["type"]) for g in r["spans"]}
        got = {(p.start, p.end, p.type) for p in pred}
        for s in sorted(gold - got):
            errors.append({"id": r["id"], "kind": "miss", "type": s[2], "text": r["text"][s[0]:s[1]]})
        for s in sorted(got - gold):
            errors.append({"id": r["id"], "kind": "extra", "type": s[2], "text": r["text"][s[0]:s[1]]})
        if (i + 1) % 10 == 0:
            print(f"{i + 1}/{len(rows)}", file=sys.stderr)

    result = {
        "date": datetime.date.today().isoformat(),
        "mode": "+".join(x for x, on in (("rules", not a.no_rules), ("llm", a.llm), ("gliner", a.gliner)) if on),
        "model": a.llm or ("gliner_multi_pii-v1" if a.gliner else None),
        "prompt_version": llm.PROMPT_VERSION if a.llm else None,
        "eval": a.eval,
        "exact": table(ex_c),
        "overlap": table(ov_c),
        "latency_ms": ({"mean": round(statistics.mean(lat)), "median": round(statistics.median(lat)),
                        "max": round(max(lat))} if lat else None),
        "linking": eval_linking(rows, a.llm),
        "errors": errors,
    }
    Path(a.out).mkdir(exist_ok=True)
    # 파이프라인 버전(PROMPT_VERSION)은 규칙·후처리 변경도 포함하므로 모든 모드에 붙인다(덮어쓰기 방지)
    tag = (f"{result['date']}_{Path(a.eval).stem}_{result['mode']}"
           + (f"_{a.llm.replace(':', '-')}" if a.llm else "") + f"_{llm.PROMPT_VERSION}")
    Path(a.out, tag + ".json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_md(result)
    Path(a.out, tag + ".md").write_text(md, encoding="utf-8")
    print(md)


def render_md(res):
    lines = [f"# {res['mode']} {res['model'] or ''} {res['prompt_version'] or ''} ({res['date']})", ""]
    lines += ["| 유형 | 완전 P | 완전 R | 완전 F1 | 겹침 P | 겹침 R | 겹침 F1 | 정답 수 |", "|---|---|---|---|---|---|---|---|"]
    for t, e in res["exact"].items():
        o = res["overlap"][t]
        lines.append(f"| {t} | {e['P']} | {e['R']} | {e['F']} | {o['P']} | {o['R']} | {o['F']} | {e['tp'] + e['fn']} |")
    lk = res["linking"]
    lines += ["", f"교차 표기 연결: 묶음 완전 일치 {lk['cluster_exact']}/{lk['n_clusters_multi']} "
                  f"({lk['cluster_exact_rate']}), 쌍 P {lk['pair_P']} / R {lk['pair_R']} / F1 {lk['pair_F']} "
                  f"(표기 {lk['n_surfaces']}개, {lk['seconds']}s)"]
    if res["latency_ms"]:
        l = res["latency_ms"]
        lines.append(f"지연(문장당, 첫 문장 제외): 평균 {l['mean']}ms / 중앙 {l['median']}ms / 최대 {l['max']}ms")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
