"""연결 판정 코드(linking.py)만 바꿨을 때: 저장된 LLM 로마자 출력으로 연결 점수를 다시 매긴다(LLM 호출 없음).

  python tools/relink.py results/2026-09-30_rules+llm_qwen3-8b_v2.json
결과 JSON의 linking 칸을 새 값으로 바꾸고, 이전 값은 linking_before로 남긴다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import eval_linking, render_md  # noqa: E402

for path in sys.argv[1:]:
    res = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in open(res["eval"], encoding="utf-8")]
    old = res["linking"]
    new = eval_linking(rows, None, saved_romans=old["romanized"])
    new["seconds"] = old["seconds"]  # LLM 호출 시간은 원래 측정값 유지
    res.setdefault("linking_before", {k: v for k, v in old.items() if k != "romanized"})
    res["linking"] = new
    Path(path).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(path).with_suffix(".md").write_text(render_md(res), encoding="utf-8")
    print(f"{Path(path).name}: {old['cluster_exact']}/9 F1 {old['pair_F']} → {new['cluster_exact']}/9 F1 {new['pair_F']}"
          f"  (쌍 P {new['pair_P']} R {new['pair_R']})")
