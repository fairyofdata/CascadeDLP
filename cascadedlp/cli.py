"""CLI — Gate를 부르는 얇은 껍데기. 사용자가 로컬에서 직접 돌리는 용도라 경로 제한이 없다.

  cascadedlp mask 메모.txt -o 메모.masked.txt            # job_id가 출력된다
  cascadedlp --project tessellane mask 설계서.md -o 설계서.masked.md   # 프로젝트 용어집 적용
  cascadedlp unmask 답변.txt --job <job_id> -o 답변.복원.txt
  cascadedlp entities                                    # 토큰·유형·표기 수 (원래 값 없음)
  cascadedlp glossary-check tessellane                   # 용어집 형식 점검
  옵션: --rules-only (LLM 없이), --model qwen3:8b, --home <폴더> (기본 ~/.cascadedlp)
"""
import argparse
import json
import sys

from .gate import Gate, GateConfig


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cascadedlp")
    ap.add_argument("--home", help="가명 맵·설정 폴더 (기본 ~/.cascadedlp 또는 CASCADEDLP_HOME)")
    ap.add_argument("--model", help="로컬 LLM 모델 (기본: config.json)")
    ap.add_argument("--rules-only", action="store_true", help="LLM 없이 규칙만")
    ap.add_argument("--project", help="적용할 프로젝트 용어집 (생략하면 config의 폴더 매핑으로 찾음)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mask")
    m.add_argument("input")
    m.add_argument("-o", "--output", required=True)
    u = sub.add_parser("unmask")
    u.add_argument("input")
    u.add_argument("--job", required=True)
    u.add_argument("-o", "--output", required=True)
    u.add_argument("--overwrite", action="store_true")
    sub.add_parser("entities")
    gc = sub.add_parser("glossary-check")
    gc.add_argument("project")
    a = ap.parse_args(argv)

    cfg = GateConfig.load(a.home)
    if a.model:
        cfg.model = a.model
    if a.rules_only:
        cfg.model = None
    gate = Gate(cfg)

    if a.cmd == "mask":
        r = gate.mask_file(a.input, a.project)
        if r.blocked:
            print(f"⛔ {r.notice}")
            return 2
        with open(a.output, "w", encoding="utf-8", newline="") as f:
            f.write(r.masked_text)
        print(f"가명화 {sum(r.counts.values())}개 {r.counts} → {a.output}  ({r.seconds}s, 용어집: {r.project or '없음'})")
        print(f"job: {r.job_id}")
        print(f"복원: cascadedlp unmask <답변파일> --job {r.job_id} -o <결과파일>")
    elif a.cmd == "unmask":
        with open(a.input, encoding="utf-8", newline="") as f:
            answer = f.read()
        info = gate.unmask_to_file(answer, a.job, a.output, overwrite=a.overwrite)
        print(f"복원 {info['restored']}/{info['tokens_in_answer']} → {info['path']}"
              + (f"  (복원 못 한 토큰 {info['unresolved']}개)" if info["unresolved"] else ""))
    elif a.cmd == "glossary-check":
        gl = gate.glossary(a.project)
        levels = {}
        for e in gl.entries:
            levels[e.effective_level] = levels.get(e.effective_level, 0) + 1
        print(f"{a.project}: 항목 {len(gl.entries)}개, 표기 {sum(len(e.surfaces) for e in gl.entries)}개, "
              f"실효 레벨별 {dict(sorted(levels.items()))}, 미확정 {sum(e.status != 'confirmed' for e in gl.entries)}개")
        for p in gl.problems:
            print(f"  ⚠ {p}")
        return 1 if gl.problems else 0
    else:
        print(json.dumps(gate.entities(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
