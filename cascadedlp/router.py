"""C5 라우터: 문서마다 로컬이 먼저 보고 어디로 보낼지 정한다 (ADR-0019의 결론: 의미가 비밀이면 가리지 말고 로컬로).

  cloud_raw           감지 없음 → 원문 그대로 클라우드
  cloud_masked        감지됨 → 가려서 클라우드 (답은 로컬에서 복원)
  needs_confirmation  의심(용어집에 없는 프로젝트 용어 후보) → 보내지 않고 로컬 대기 목록에 올려 사용자 확인
  local_only          L3(의미가 비밀) 용어 포함 → 로컬 모델만 처리, 결과는 로컬 파일, 호출자에게는 경로만
  block               처리할 수 없음 → 어디로도 보내지 않음: 비밀키(secret_policy=block), 원문에 토큰 모양,
                      의심 항목 과다, 가릴 비율 과다

판단 순서: block(비밀키·토큰 모양) → local_only → block(의심 과다) → needs_confirmation → block(가릴 비율) → raw/masked

라우팅 단위는 문서 전체(의미는 문서 흐름으로 새므로). 모든 결정은 감사 로그에 남긴다(내용 없이).
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import llm, rules
from .bootstrap import key, term_candidates
from .confirm import add_pending, load_allow, project_dir
from .gate import Gate
from .pseudo import TOKEN_RE

ROUTES = ("cloud_raw", "cloud_masked", "needs_confirmation", "local_only", "block")
LOCAL_MAX_CHARS = 12000
LOCAL_SYSTEM = """You are a local assistant. Answer the user's request using the document. Be concise and accurate.
Answer in the same language as the request."""


@dataclass
class RouteResult:
    route: str
    reasons: list[str]
    counts: dict = field(default_factory=dict)
    text: str = ""                 # cloud_raw: 원문 / cloud_masked: 가린 텍스트
    job_id: str = ""
    local_answer_path: str = ""    # local_only: 로컬 답 파일
    notice: str = ""
    n_suspects: int = 0            # needs_confirmation: 의심 항목 수 (내용은 로컬 pending.md에만)
    pending_path: str = ""


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def audit(gate: Gate, event: dict):
    """~/.cascadedlp/audit.jsonl 에 한 줄. 내용·경로 원문은 남기지 않는다(해시·개수·결정만)."""
    gate.cfg.home.mkdir(parents=True, exist_ok=True)
    event = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    with open(gate.cfg.home / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def local_answer(model: str, text: str, question: str) -> str:
    doc = text[:LOCAL_MAX_CHARS]
    note = "" if len(text) <= LOCAL_MAX_CHARS else f"\n\n(문서가 길어 앞 {LOCAL_MAX_CHARS}자만 사용)"
    body = {"model": model, "stream": False, "think": False, "options": {"temperature": 0.2, "num_ctx": 8192},
            "messages": [{"role": "system", "content": LOCAL_SYSTEM},
                         {"role": "user", "content": f"{doc}\n\n---\n요청: {question}"}]}
    r = requests.post(llm.OLLAMA_URL, json=body, timeout=900)
    r.raise_for_status()
    return r.json()["message"]["content"].strip() + note


def route_text(gate: Gate, text: str, project: str | None = None, question: str | None = None,
               local_out: str | Path | None = None, source_hash: str = "") -> RouteResult:
    """문서를 분석해 경로를 정하고, 그 경로에 맞는 결과를 만든다."""
    policy = getattr(gate.cfg, "secret_policy", "block")
    secrets_found = sum(s.type == "SECRET" for s in rules.detect(text))
    if secrets_found and policy == "block":
        res = RouteResult("block", [f"비밀키 형식 {secrets_found}건"],
                          notice="비밀키가 있어 어디로도 보내지 않았습니다. 키를 빼거나 secret_policy를 mask로 바꾸세요.")
    elif TOKEN_RE.search(text):
        res = RouteResult("block", ["원문에 [TYPE_01] 모양의 문자열이 있음"],
                          notice="원문에 가명 토큰과 같은 모양의 문자열이 있어 복원이 모호해집니다. 그 부분을 바꾼 뒤 다시 시도하세요.")
    else:
        m = gate.mask_text(text, project)
        if m.blocked:  # L3
            res = RouteResult("local_only", ["L3(외부 금지) 용어 포함"], notice=m.notice)
            if question and gate.cfg.model:
                if not local_out:
                    raise ValueError("local_only 결과를 쓸 로컬 파일 경로(local_out)가 필요합니다.")
                out = gate._check(local_out)
                if out.exists():
                    raise FileExistsError(f"이미 있는 파일은 덮어쓰지 않습니다: {out}")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(local_answer(gate.cfg.model, text, question), encoding="utf-8")
                res.local_answer_path = str(out)
                res.notice = "L3 용어가 있어 로컬 모델이 처리했습니다. 결과는 로컬 파일에만 있습니다."
        else:
            restore = gate._restore_table(m.job_id)
            suspects = find_suspects(gate, text, project, restore)
            masked_chars = sum(len(x["surface"]) for x in restore)
            if len(suspects) > gate.cfg.max_suspects:
                res = RouteResult("block", [f"의심 항목 과다({len(suspects)}건)"], n_suspects=len(suspects),
                                  notice=f"용어집에 없는 프로젝트 용어 후보가 너무 많습니다. 먼저 용어집을 만드세요: "
                                         f"cascadedlp --project {project} bootstrap <문서 폴더>")
            elif suspects:  # 의심되는 것은 사용자에게 확인 — 확인 전에는 보내지 않는다
                pdir = project_dir(gate.cfg.home, project)
                left = add_pending(pdir, project, suspects)
                res = RouteResult("needs_confirmation", [f"용어집에 없는 프로젝트 용어 후보 {len(suspects)}건"],
                                  n_suspects=len(suspects), pending_path=str(pdir / "pending.md"),
                                  notice=f"확인이 필요한 항목이 있어 보내지 않았습니다(대기 {left}건). 로컬에서 "
                                         f"{pdir / 'pending.md'} 를 열어 [x] 보호 / [o] 일반어로 표시한 뒤 "
                                         f"`cascadedlp --project {project} confirm` 을 실행하고 다시 요청하세요.")
            elif len(text) >= 300 and masked_chars / len(text) >= gate.cfg.max_masked_ratio:
                res = RouteResult("block", [f"가릴 비율 {masked_chars / len(text):.0%}"],
                                  notice="가려야 할 부분이 너무 많아 클라우드 모델이 일할 수 없습니다. 로컬에서 처리하세요.")
            elif not m.counts:
                res = RouteResult("cloud_raw", ["민감 항목 없음"], text=text, job_id=m.job_id)
            else:
                reasons = [f"{k} {v}건" for k, v in sorted(m.counts.items())]
                res = RouteResult("cloud_masked", reasons, counts=m.counts, text=m.masked_text, job_id=m.job_id)
    audit(gate, {"route": res.route, "source": source_hash or sha(text), "project": project,
                 "chars_in": len(text), "chars_out": len(res.text), "counts": res.counts,
                 "reasons": res.reasons, "job_id": res.job_id, "local_answer": bool(res.local_answer_path),
                 "suspects": res.n_suspects})
    return res


def find_suspects(gate: Gate, text: str, project: str | None, restore: list[dict]) -> list[dict]:
    """용어집에도 허용 목록에도 없고, 이미 가려지지도 않는 '프로젝트 용어처럼 생긴 말'.
    프로젝트(용어집)가 없거나 로컬 LLM이 없으면 검사하지 않는다(기준이 없으면 모든 고유명이 의심이 된다)."""
    if not project or not gate.cfg.model:
        return []
    known = {key(s) for e in gate.glossary(project).entries for s in e.surfaces}
    known |= load_allow(project_dir(gate.cfg.home, project))
    masked = {key(x["surface"]) for x in restore} - {""}
    out = []
    for k, c in term_candidates(text, gate.cfg.model).items():
        if not k or k in known or k in masked:
            continue
        if any(m in k or k in m for m in masked) or any(n in k for n in known if len(n) >= 3):
            continue  # 이미 가려진 것의 일부이거나, 아는 용어에 일반어가 붙은 긴 변형
        out.append(c)
    return out


def route_file(gate: Gate, path: str | Path, project: str | None = None, question: str | None = None,
               local_out: str | Path | None = None) -> RouteResult:
    p = gate._check(path)
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    return route_text(gate, text, gate.project_for(p, project), question, local_out, source_hash=sha(str(p)))
