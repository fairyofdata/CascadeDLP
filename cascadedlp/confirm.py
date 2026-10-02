"""C7 의심 항목 확인: 용어집에 없는 '프로젝트 용어처럼 생긴 말'을 사용자가 로컬에서 판정한다.

~/.cascadedlp/projects/<프로젝트>/
  pending.md   대기 목록(체크리스트). [x] 보호(용어집에 추가) · [o] 일반어(허용 목록에 추가) · [ ] 아직 미정
  allow.json   일반어로 판정한 표기 — 다시 묻지 않는다
한 번 답한 것은 기억한다. 🔴 pending.md도 '무엇이 핵심일 수 있는가'의 목록이라 로컬 전용(MCP·외부 LLM에 내용 전달 금지).
"""
import json
import re
from pathlib import Path

from .bootstrap import apply_review, key

_HEAD = re.compile(r"^## \[(x|X|o|O| )\] P(\d+) · (.+)$")
HELP = [
    "# 확인 대기 — {project}",
    "",
    "> ⚠ 이 파일은 로컬 전용이다. 공유·커밋·외부 LLM 전송 금지.",
    "> 용어집에 없는데 프로젝트 고유 용어처럼 보여서 문서 전송을 보류했다. 항목마다 표시한다:",
    "> `[x]` 보호 대상 → 용어집에 추가 (kind·level·설명·표기를 고칠 수 있다. level: 1 설명만 · 2 토큰 · 3 외부 금지)",
    "> `[o]` 일반어·공개 용어 → 허용 목록에 추가 (다시 묻지 않는다)",
    "> `[ ]` 아직 미정 → 그대로 남는다 (이 표기가 나오는 문서는 계속 보류)",
    "> 끝나면: `cascadedlp --project {project} confirm`",
    "",
]


def project_dir(home: Path, project: str) -> Path:
    return Path(home) / "projects" / project


def load_allow(pdir: Path) -> set[str]:
    p = pdir / "allow.json"
    return {key(s) for s in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else set()


def parse_pending(md: str) -> list[dict]:
    items, cur = [], None
    for line in md.splitlines():
        m = _HEAD.match(line)
        if m:
            cur = {"state": m.group(1).lower().strip() or " ", "n": int(m.group(2)), "title": m.group(3).strip(),
                   "kind": "TERM", "level": 2, "alias": "", "surfaces": [m.group(3).strip()]}
            items.append(cur)
        elif cur:
            f = re.match(r"^- (kind|level|설명|표기):\s*(.*)$", line)
            if f:
                name, v = f.group(1), f.group(2).strip()
                if name == "kind":
                    cur["kind"] = v.upper() or "TERM"
                elif name == "level":
                    cur["level"] = int(v[:1]) if v[:1].isdigit() else 2
                elif name == "설명":
                    cur["alias"] = v
                else:
                    cur["surfaces"] = [s.strip() for s in v.split("|") if s.strip()] or cur["surfaces"]
    return items


def render_pending(items: list[dict], project: str) -> str:
    lines = [h.format(project=project) for h in HELP]
    for it in items:
        lines += [f"## [{it['state']}] P{it['n']:03d} · {it['title']}",
                  f"- kind: {it['kind']}", f"- level: {it['level']}", f"- 설명: {it['alias']}",
                  f"- 표기: {' | '.join(it['surfaces'])}", ""]
    return "\n".join(lines)


def add_pending(pdir: Path, project: str, suspects: list[dict]) -> int:
    """새 의심 항목을 대기 목록에 더한다(이미 있는 표기는 건너뜀). → 현재 미정 항목 수"""
    path = pdir / "pending.md"
    items = parse_pending(path.read_text(encoding="utf-8")) if path.exists() else []
    known = {key(s) for it in items for s in it["surfaces"]}
    n = max((it["n"] for it in items), default=0)
    for s in suspects:
        if key(s["surface"]) in known:
            continue
        n += 1
        known.add(key(s["surface"]))
        items.append({"state": " ", "n": n, "title": s["surface"], "kind": s.get("kind", "TERM"), "level": 2,
                      "alias": s.get("desc", ""), "surfaces": [s["surface"]]})
    pdir.mkdir(parents=True, exist_ok=True)
    path.write_text(render_pending(items, project), encoding="utf-8")
    return sum(it["state"] == " " for it in items)


def apply_pending(pdir: Path, project: str) -> dict:
    """[x] → 용어집(confirmed), [o] → 허용 목록, [ ] → 남김."""
    path = pdir / "pending.md"
    if not path.exists():
        return {"protected": 0, "allowed": 0, "left": 0}
    items = parse_pending(path.read_text(encoding="utf-8"))
    protect = [it for it in items if it["state"] == "x"]
    allow = [it for it in items if it["state"] == "o"]
    left = [it for it in items if it["state"] == " "]
    if protect:  # 부트스트랩 검토 파일과 같은 형식으로 바꿔 apply_review 재사용(표기 겹치면 기존 항목에 보강)
        md = "\n".join(f"## [x] C{it['n']:03d} · {it['title']}\n- kind: {it['kind']}\n- level: {it['level']}\n"
                       f"- 설명: {it['alias']}\n- 표기: {' | '.join(it['surfaces'])}\n" for it in protect)
        apply_review(md, pdir / "glossary.json", project)
    if allow:
        ap = pdir / "allow.json"
        cur = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else []
        cur += [s for it in allow for s in it["surfaces"] if s not in cur]
        ap.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    path.write_text(render_pending(left, project), encoding="utf-8")
    return {"protected": len(protect), "allowed": len(allow), "left": len(left)}
