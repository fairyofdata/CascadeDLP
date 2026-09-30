"""C5 라우터: 문서마다 로컬이 먼저 보고 어디로 보낼지 정한다 (ADR-0019의 결론: 의미가 비밀이면 가리지 말고 로컬로).

  cloud_raw     민감한 것이 없음 → 원문 그대로 클라우드
  cloud_masked  이름·개인정보·L1/L2 용어만 → 가려서 클라우드 (복원은 로컬)
  local_only    L3(의미가 비밀) 용어 포함 → 로컬 모델만 처리, 결과는 로컬 파일, 호출자에게는 경로만
  block         비밀키 등(secret_policy=block) → 어디로도 보내지 않음

라우팅 단위는 문서 전체(의미는 문서 흐름으로 새므로). 모든 결정은 감사 로그에 남긴다(내용 없이).
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import llm, rules
from .gate import Gate

ROUTES = ("cloud_raw", "cloud_masked", "local_only", "block")
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
        elif not m.counts:
            res = RouteResult("cloud_raw", ["민감 항목 없음"], text=text, job_id=m.job_id)
        else:
            reasons = [f"{k} {v}건" for k, v in sorted(m.counts.items())]
            res = RouteResult("cloud_masked", reasons, counts=m.counts, text=m.masked_text, job_id=m.job_id)
    audit(gate, {"route": res.route, "source": source_hash or sha(text), "project": project,
                 "chars_in": len(text), "chars_out": len(res.text), "counts": res.counts,
                 "reasons": res.reasons, "job_id": res.job_id, "local_answer": bool(res.local_answer_path)})
    return res


def route_file(gate: Gate, path: str | Path, project: str | None = None, question: str | None = None,
               local_out: str | Path | None = None) -> RouteResult:
    p = gate._check(path)
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    return route_text(gate, text, gate.project_for(p, project), question, local_out, source_hash=sha(str(p)))
