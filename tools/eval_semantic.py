"""C3·C6 측정: 가림 방식별 효용 / 이름 유출 / 의미 유출을 한 표로.

  python tools/eval_semantic.py data/eval/c2_dev_tessellane qwen3.5:9b

가림 방식 (문서는 방식마다 한 번만 가리고 효용·공격 질문이 같이 쓴다):
  raw         원문
  alias       용어집 전체 L1 (설명형 별칭)
  opaque      용어집 전체 L2, 문장 그대로 (keep)
  generalize  L2 + L2 항목이 나오는 문장을 로컬 LLM이 '어떻게'를 빼고 다시 씀
  drop        L2 + L2 항목이 나오는 문장 제거
효용: qa.json 질문 정답률 (질문도 같은 용어집으로 가림, 답은 로컬 복원 후 채점)
이름 유출: 보낸 문서에 드러난 보호 용어 수
의미 유출: 공격자(로컬 모델)가 가린 문서만 보고 설명한 내용에 gold.json 'secrets' 사실이 몇 개 들어 있나(키워드)
          + 원래 이름을 맞혔나
"""
import json
import re
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp import llm  # noqa: E402
from cascadedlp.gate import Gate, GateConfig  # noqa: E402
from cascadedlp.glossary import surface_pattern  # noqa: E402
from cascadedlp.pseudo import PseudoMap, unmask  # noqa: E402

SEMANTIC_PROMPT_VERSION = "s1"
MODES = ["raw", "alias", "opaque", "generalize", "drop"]
MAX_CONTEXT_CHARS = 6000

ANSWER_SYSTEM = """Answer the question at the end using only the documents above it. Answer in one short sentence.
Some names are hidden as placeholder tokens like [COMPONENT_01] or [COMPONENT_01: short description].
If the answer is a hidden name, write its token exactly (e.g. [COMPONENT_01]); never invent a real-looking name."""
ATTACK_SYSTEM = """You analyze internal documents in which some names are hidden as placeholder tokens like [ALGORITHM_01].
Using only the documents, explain the target in Korean as specifically as you can:
1) 무엇인가 2) 무엇을 하며 어떻게 동작하는가 — 단계, 수치, 시간, 다른 구성요소와의 관계까지
3) 원래 이름 추측 (모르면 '모름')."""

_orig_detect = llm.detect


@lru_cache(maxsize=None)
def _cached_detect(chunk, model):
    return _orig_detect(chunk, model)


llm.detect = lambda chunk, model: _cached_detect(chunk, model)   # 같은 조각의 개인정보 탐지는 방식이 달라도 같다


def chat(model, system, user, predict=None):
    opts = {"temperature": 0, "num_ctx": 8192}
    if predict:
        opts["num_predict"] = predict
    body = {"model": model, "stream": False, "think": False, "options": opts,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = requests.post(llm.OLLAMA_URL, json=body, timeout=900)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def main(folder, model):
    folder = Path(folder)
    gold = json.loads((folder / "gold.json").read_text(encoding="utf-8"))
    qa = json.loads((folder / "qa.json").read_text(encoding="utf-8"))["items"]
    docs = {p.name: p.read_text(encoding="utf-8") for p in sorted((folder / "docs").glob("*.md"))}
    protected = [re.compile(surface_pattern(s), re.IGNORECASE) for e in gold["entries"] for s in e["surfaces"]]
    targets = [e for e in gold["entries"] if e.get("secrets")]

    res = {m: {"qa_correct": 0, "qa_total": 0, "term_exposed": 0, "facts": 0, "facts_leaked": 0,
               "names_recovered": 0, "mask_seconds": 0.0} for m in MODES}
    detail = {m: {"qa": [], "attack": []} for m in MODES}
    with tempfile.TemporaryDirectory() as home:
        home = Path(home)
        for proj, level in (("alias", 1), ("l2", 2)):
            entries = [{"id": e["id"], "kind": e["kind"], "level": level, "status": "confirmed",
                        "surfaces": e["surfaces"], "alias": e["alias"]} for e in gold["entries"]]
            (home / "projects" / proj).mkdir(parents=True)
            (home / "projects" / proj / "glossary.json").write_text(
                json.dumps({"project": proj, "entries": entries}, ensure_ascii=False), encoding="utf-8")
        gate = Gate(GateConfig(home=home, model=model, link=False))
        pmap = lambda: PseudoMap(gate.map_path)  # noqa: E731

        for mode in MODES:
            proj = {"raw": None, "alias": "alias"}.get(mode, "l2")
            ctx = {"generalize": "generalize", "drop": "drop"}.get(mode, "keep")
            masked, restores = {}, {}
            t0 = time.perf_counter()
            for name, text in docs.items():
                if mode == "raw":
                    masked[name], restores[name] = text, []
                else:
                    r = gate.mask_text(text, proj, l2_context=ctx)
                    masked[name], restores[name] = r.masked_text, gate._restore_table(r.job_id)
            st = res[mode]
            st["mask_seconds"] = round(time.perf_counter() - t0, 1)
            st["term_exposed"] = sum(len(p.findall(t)) for p in protected for t in masked.values())

            # 효용
            for it in qa:
                if mode == "raw":
                    q, q_restore = it["q"], []
                else:
                    rq = gate.mask_text(it["q"], proj)
                    q, q_restore = rq.masked_text, gate._restore_table(rq.job_id)
                ans = chat(model, ANSWER_SYSTEM, f"{masked[it['doc']]}\n\n---\nQuestion: {q}")
                restored = ans if mode == "raw" else unmask(ans, restores[it["doc"]] + q_restore, pmap())
                ok = any(a.casefold() in restored.casefold() for a in it["answers"])
                st["qa_total"] += 1
                st["qa_correct"] += ok
                detail[mode]["qa"].append({"q": it["q"], "ok": ok, "answer": restored})

            # 의미 유출: 그 항목이 원문에 나오는 문서들의 가린 버전만 준다
            for e in targets:
                pats = [re.compile(surface_pattern(s), re.IGNORECASE) for s in e["surfaces"]]
                related = [n for n, t in docs.items() if any(p.search(t) for p in pats)]
                context = "\n\n".join(f"### {n}\n{masked[n]}" for n in related)[:MAX_CONTEXT_CHARS]
                target = e["surfaces"][0] if mode == "raw" else f"[{e['id']}]"
                ans = chat(model, ATTACK_SYSTEM, f"{context}\n\n---\n대상: {target}", predict=400)
                low = ans.casefold()
                hits = [s["fact"] for s in e["secrets"] if any(k.casefold() in low for k in s["keywords"])]
                named = mode != "raw" and any(s.casefold() in low for s in e["surfaces"])
                st["facts"] += len(e["secrets"])
                st["facts_leaked"] += len(hits)
                st["names_recovered"] += named
                detail[mode]["attack"].append({"id": e["id"], "facts_hit": hits, "name_recovered": named, "answer": ans})
            print(f"{mode}: done", file=sys.stderr)

    for st in res.values():
        st["qa_accuracy"] = round(st["qa_correct"] / st["qa_total"], 3)
        st["semantic_leak"] = round(st["facts_leaked"] / st["facts"], 3)
    out = {"corpus": folder.name, "model": model, "pipeline_version": llm.PROMPT_VERSION,
           "semantic_prompt_version": SEMANTIC_PROMPT_VERSION, "results": res, "detail": detail}
    tag = f"c6_semantic_{folder.name}_{model.replace(':', '-')}_{llm.PROMPT_VERSION}_{SEMANTIC_PROMPT_VERSION}"
    Path("results", tag + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'방식':11s} {'효용':>7s} {'이름노출':>6s} {'의미유출':>9s} {'이름복원':>6s} {'가림시간':>7s}")
    for m in MODES:
        s = res[m]
        print(f"{m:11s} {s['qa_correct']:>3d}/{s['qa_total']:<3d} {s['term_exposed']:>6d} "
              f"{s['facts_leaked']:>3d}/{s['facts']:<3d}({s['semantic_leak']:.2f}) {s['names_recovered']:>5d} {s['mask_seconds']:>7.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
