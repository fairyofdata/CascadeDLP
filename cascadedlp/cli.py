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

from .confirm import apply_pending, project_dir
from .gate import Gate, GateConfig
from .router import audit, route_file, sha


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
    bs = sub.add_parser("bootstrap", help="문서 폴더에서 용어집 후보 검토 md를 만든다 (--project 필요)")
    bs.add_argument("folder")
    bs.add_argument("-o", "--output", help="검토 md (기본 ~/.cascadedlp/projects/<프로젝트>/review.md)")
    ar = sub.add_parser("apply-review", help="체크한 후보를 용어집에 반영 (--project 필요)")
    ar.add_argument("review")
    rt = sub.add_parser("route", help="문서를 보고 경로 결정: cloud_raw / cloud_masked / local_only / block")
    rt.add_argument("input")
    rt.add_argument("-q", "--question", help="local_only일 때 로컬 모델에 시킬 요청")
    rt.add_argument("-o", "--output", help="cloud_*: 보낼 텍스트 파일 / local_only: 로컬 답 파일")
    sub.add_parser("confirm", help="확인 대기 목록(pending.md)의 표시를 반영: [x] 보호 → 용어집, [o] 일반어 → 허용 (--project 필요)")
    au = sub.add_parser("audit", help="감사 로그 최근 기록 (내용 없이 해시·개수·경로)")
    au.add_argument("-n", type=int, default=20)
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
        audit(gate, {"route": "cloud_masked", "source": sha(a.input), "project": r.project, "chars_out": len(r.masked_text),
                     "counts": r.counts, "job_id": r.job_id, "via": "cli mask"})
        print(f"가명화 {sum(r.counts.values())}개 {r.counts} → {a.output}  ({r.seconds}s, 용어집: {r.project or '없음'})")
        print(f"job: {r.job_id}")
        print(f"복원: cascadedlp unmask <답변파일> --job {r.job_id} -o <결과파일>")
    elif a.cmd == "unmask":
        with open(a.input, encoding="utf-8", newline="") as f:
            answer = f.read()
        info = gate.unmask_to_file(answer, a.job, a.output, overwrite=a.overwrite)
        print(f"복원 {info['restored']}/{info['tokens_in_answer']} → {info['path']}"
              + (f"  (복원 못 한 토큰 {info['unresolved']}개)" if info["unresolved"] else ""))
    elif a.cmd in ("bootstrap", "apply-review"):
        from pathlib import Path

        from .bootstrap import apply_review, bootstrap, render_review
        project = gate.project_for(project=a.project) if a.project else None
        if not project:
            print("--project <이름> 이 필요합니다.")
            return 1
        pdir = cfg.home / "projects" / project
        if a.cmd == "bootstrap":
            if not cfg.model:
                print("부트스트랩에는 로컬 LLM이 필요합니다(--rules-only 불가).")
                return 1
            out = Path(a.output) if a.output else pdir / "review.md"
            if out.exists():
                print(f"이미 있습니다(검토 중인 내용 보호): {out} — 지우거나 -o로 다른 이름을 주세요.")
                return 1
            res = bootstrap(a.folder, cfg.model)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_review(res, project), encoding="utf-8")
            print(f"후보 {len(res.groups)}개 (제외 {len(res.excluded)}개), 문서 {res.n_docs}개, "
                  f"LLM {res.llm_calls}회, {res.seconds}s → {out}")
            print("⚠ 이 파일은 '무엇이 핵심인가'의 초안입니다. 공유·커밋·외부 전송 금지.")
        else:
            info = apply_review(Path(a.review).read_text(encoding="utf-8"), pdir / "glossary.json", project)
            print(f"추가 {info['added']}개, 표기 보강 {info['extended']}개 → 전체 {info['total']}개 ({info['path']})")
            print(f"점검: cascadedlp glossary-check {project}")
    elif a.cmd == "route":
        cloud = None
        r = route_file(gate, a.input, a.project, a.question, a.output if a.question else None)
        print(f"경로: {r.route}  ({', '.join(r.reasons)})")
        if r.notice:
            print(f"  {r.notice}")
        if r.route in ("cloud_raw", "cloud_masked"):
            cloud = r.text
            if a.output:
                with open(a.output, "w", encoding="utf-8", newline="") as f:
                    f.write(cloud)
                print(f"  보낼 텍스트 → {a.output}" + (f"  (복원 job: {r.job_id})" if r.route == "cloud_masked" else ""))
        if r.local_answer_path:
            print(f"  로컬 답 → {r.local_answer_path}")
        return {"block": 3, "local_only": 2, "needs_confirmation": 4}.get(r.route, 0)
    elif a.cmd == "confirm":
        if not a.project:
            print("--project <이름> 이 필요합니다.")
            return 1
        project = gate.project_for(project=a.project)
        info = apply_pending(project_dir(cfg.home, project), project)
        print(f"보호(용어집에 추가) {info['protected']}건, 일반어(허용) {info['allowed']}건, 아직 미정 {info['left']}건")
        if info["left"]:
            print(f"  미정 항목이 나오는 문서는 계속 보류됩니다: {project_dir(cfg.home, project) / 'pending.md'}")
    elif a.cmd == "audit":
        path = cfg.home / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()[-a.n:] if path.exists() else []
        for line in lines:
            e = json.loads(line)
            print(f"{e['time']}  {e['route']:12s} {e.get('project') or '-':12s} out {e.get('chars_out', 0):>6}자  "
                  f"{e.get('counts') or ''}")
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
