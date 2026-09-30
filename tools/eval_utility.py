"""C6 측정: 가림 방식별 효용(질문 정답률) 대 유출(보호 용어·사람 이름 노출).

  python tools/eval_utility.py data/eval/c2_dev_tessellane qwen3.5:9b

'클라우드 모델' 자리는 로컬 모델로 대신한다(사용자 선택) — 가림 방식끼리의 상대 비교용.
흐름: (문서 + 질문)을 한 텍스트로 가림 → 답하는 모델 → 답을 로컬에서 복원 → 허용 표기 포함 여부로 채점.
가림 방식:
  raw     원문 그대로
  pii     개인정보만 (규칙 + 로컬 LLM)
  alias   개인정보 + 용어집 전체 L1 (설명형 별칭 [X_01: 설명])
  opaque  개인정보 + 용어집 전체 L2 (불투명 토큰 [X_01])
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp.gate import Gate, GateConfig  # noqa: E402
from cascadedlp.glossary import surface_pattern  # noqa: E402
from cascadedlp.llm import OLLAMA_URL, PROMPT_VERSION  # noqa: E402

UTILITY_PROMPT_VERSION = "u1"
MODES = ["raw", "pii", "alias", "opaque"]
ANSWER_SYSTEM = """Answer the question at the end using only the document above it. Answer in one short sentence.
Some names are hidden as placeholder tokens like [COMPONENT_01] or [COMPONENT_01: short description].
If the answer is a hidden name, write its token exactly (e.g. [COMPONENT_01]); never invent a real-looking name."""


def answer(model: str, text: str) -> str:
    body = {"model": model, "stream": False, "think": False,
            "messages": [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": text}],
            "options": {"temperature": 0, "num_ctx": 8192}}
    r = requests.post(OLLAMA_URL, json=body, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def main(folder, model):
    folder = Path(folder)
    gold = json.loads((folder / "gold.json").read_text(encoding="utf-8"))
    qa = json.loads((folder / "qa.json").read_text(encoding="utf-8"))["items"]
    protected = [re.compile(surface_pattern(s), re.IGNORECASE) for e in gold["entries"] for s in e["surfaces"]]
    persons = [re.compile(re.escape(p)) for p in gold.get("persons", [])]

    results = {m: {"correct": 0, "total": 0, "term_exposed": 0, "person_exposed": 0, "seconds": 0.0} for m in MODES}
    items = []
    with tempfile.TemporaryDirectory() as home:
        home = Path(home)
        for mode, level in (("alias", 1), ("opaque", 2)):
            entries = [{"id": e["id"], "kind": e["kind"], "level": level, "status": "confirmed",
                        "surfaces": e["surfaces"], "alias": e["alias"]} for e in gold["entries"]]
            (home / "projects" / mode).mkdir(parents=True)
            (home / "projects" / mode / "glossary.json").write_text(
                json.dumps({"project": mode, "entries": entries}, ensure_ascii=False), encoding="utf-8")
        gate = Gate(GateConfig(home=home, model=model, link=False))
        for n, it in enumerate(qa, 1):
            doc = (folder / "docs" / it["doc"]).read_text(encoding="utf-8")
            text = f"{doc}\n\n---\nQuestion: {it['q']}"
            row = {"doc": it["doc"], "q": it["q"]}
            for mode in MODES:
                t0 = time.perf_counter()
                if mode == "raw":
                    sent, job = text, None
                else:
                    r = gate.mask_text(text, None if mode == "pii" else mode)
                    sent, job = r.masked_text, r.job_id
                ans = answer(model, sent)
                restored = gate.unmask_text(ans, job) if job else ans
                ok = any(a.casefold() in restored.casefold() for a in it["answers"])
                st = results[mode]
                st["total"] += 1
                st["correct"] += ok
                st["term_exposed"] += sum(len(p.findall(sent)) for p in protected)
                st["person_exposed"] += sum(len(p.findall(sent)) for p in persons)
                st["seconds"] += time.perf_counter() - t0
                row[mode] = {"ok": ok, "answer": ans, "restored": restored}
            items.append(row)
            print(f"{n}/{len(qa)} " + " ".join(f"{m}:{'O' if row[m]['ok'] else 'X'}" for m in MODES), file=sys.stderr)

    for st in results.values():
        st["accuracy"] = round(st["correct"] / st["total"], 3)
        st["seconds"] = round(st["seconds"], 1)
    out = {"corpus": folder.name, "model": model, "pipeline_version": PROMPT_VERSION,
           "utility_prompt_version": UTILITY_PROMPT_VERSION, "results": results, "items": items}
    tag = f"c6_utility_{folder.name}_{model.replace(':', '-')}_{PROMPT_VERSION}_{UTILITY_PROMPT_VERSION}"
    Path("results", tag + ".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'mode':7s} {'정답률':>6s} {'용어 노출':>8s} {'이름 노출':>8s}")
    for m in MODES:
        s = results[m]
        print(f"{m:7s} {s['correct']:>3d}/{s['total']:<3d} {s['term_exposed']:>8d} {s['person_exposed']:>8d}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:9b")
