"""문서 단위 개인정보 탐지 측정: 합성 문서(c2 두 프로젝트, 10개)에서 사람 이름이 새는가, 숫자·시각을 과잉 가림하는가.

  python tools/eval_doc_pii.py qwen3.5:9b 1500 300      # 탐지 조각 크기별 비교

1단계 평가(eval_v1·v2)는 문장 단위라 긴 입력에서의 약점이 안 보였다(C6에서 발견).
- 이름 노출: gold.json persons 표기가 가린 텍스트에 남은 횟수 / 원문 등장 횟수
- 질문을 붙인 변형도 같이 본다(입력 모양이 조금 바뀌면 탐지가 흔들리는지)
- 숫자 과잉 가림: 복원표에서 숫자·시각·기호만으로 된 표기를 가린 횟수
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cascadedlp import gate as gate_mod  # noqa: E402
from cascadedlp.gate import Gate, GateConfig  # noqa: E402
from cascadedlp.llm import PROMPT_VERSION  # noqa: E402

CORPORA = ["data/eval/c2_dev_tessellane", "data/eval/c2_holdout_quillmere"]
NUMERIC = re.compile(r"[\d\s:.,/~\-%]+")


def run(model, chunk):
    gate_mod.DETECT_CHUNK_CHARS = chunk
    st = {"chunk": chunk, "names_total": 0, "names_leaked": 0, "names_leaked_with_q": 0,
          "numeric_over_masked": 0, "seconds": 0.0, "leaks": []}
    with tempfile.TemporaryDirectory() as home:
        g = Gate(GateConfig(home=Path(home), model=model, link=False))
        for c in CORPORA:
            persons = json.loads(Path(c, "gold.json").read_text(encoding="utf-8"))["persons"]
            for doc in sorted(Path(c, "docs").glob("*.md")):
                text = doc.read_text(encoding="utf-8")
                for variant, t in (("doc", text), ("with_q", text + "\n\n---\nQuestion: 이 문서의 요점은?")):
                    t0 = time.perf_counter()
                    r = g.mask_text(t)
                    st["seconds"] += time.perf_counter() - t0
                    for p in persons:
                        n_src, n_left = t.count(p), r.masked_text.count(p)
                        if variant == "doc":
                            st["names_total"] += n_src
                            st["names_leaked"] += n_left
                        else:
                            st["names_leaked_with_q"] += n_left
                        if n_left:
                            st["leaks"].append(f"{variant}:{doc.name}:{p}×{n_left}")
                    if variant == "doc":
                        st["numeric_over_masked"] += sum(bool(NUMERIC.fullmatch(x["surface"]))
                                                         for x in g._restore_table(r.job_id))
    st["seconds"] = round(st["seconds"], 1)
    return st


def main(model, chunks):
    out = {"model": model, "pipeline_version": PROMPT_VERSION, "runs": [run(model, int(c)) for c in chunks]}
    Path("results", f"doc_pii_{model.replace(':', '-')}_{PROMPT_VERSION}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in out["runs"]:
        print(f"조각 {s['chunk']:>5}자: 이름 노출 {s['names_leaked']}/{s['names_total']} "
              f"(질문 붙이면 {s['names_leaked_with_q']}), 숫자 과잉 가림 {s['numeric_over_masked']}, {s['seconds']}s")
        for x in s["leaks"]:
            print("   ", x)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["1500", "300"])
