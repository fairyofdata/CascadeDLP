"""Gate — CascadeDLP의 중심 API. CLI·MCP 서버는 이걸 부르는 얇은 껍데기다.

    from cascadedlp.gate import Gate
    g = Gate()                                   # 설정은 ~/.cascadedlp/config.json (없으면 기본값)
    r = g.mask_file("메모.txt")                   # → r.masked_text 를 외부 LLM에 보낸다
    g.unmask_to_file(llm_answer, r.job_id, "답변_복원.txt")   # 복원은 로컬 파일로만

경계 원칙 (PLAN.md '레이어화 설계'):
- 호출자(외부 LLM일 수 있음)에게 주는 것은 가명화된 텍스트·job_id·유형별 개수뿐.
- 원래 값은 가명 맵과 복원표(로컬, ~/.cascadedlp)와 복원 결과 파일에만 존재한다.
- restrict_paths=True(MCP)면 허용 폴더 안의 파일만 읽고, 그 안에만 새 파일로 쓴다.
"""
import json
import os
import re
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import linking, llm, rules
from .glossary import Glossary
from .pseudo import TOKEN_RE, PseudoMap, mask, unmask
from .spans import Span, resolve

MAX_LINK_SURFACES = 200
CHUNK_CHARS = 1500   # LLM 탐지 1회에 넣는 최대 글자 수 (한·일 1500자 ≈ 수천 토큰, 8K 컨텍스트에 여유)


def chunks(text: str, limit: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """줄 단위로 limit 글자 이하 조각으로 나눈다 → [(시작 위치, 조각)]. 한 줄이 limit보다 길면 문장부호·공백에서 자른다."""
    pieces = []
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # 아주 긴 한 줄: limit 안쪽 마지막 문장부호·공백 뒤에서 자른다
            cut = max(line.rfind(c, 0, limit) for c in "。．.!?！？ \t、,") + 1
            if cut <= 0:
                cut = limit
            pieces.append(line[:cut])
            line = line[cut:]
        pieces.append(line)
    out, start, buf = [], 0, ""
    for piece in pieces:  # 조각들을 limit 이하로 다시 모은다
        if buf and len(buf) + len(piece) > limit:
            out.append((start, buf))
            start += len(buf)
            buf = ""
        buf += piece
    if buf:
        out.append((start, buf))
    return out


def default_home() -> Path:
    return Path(os.environ.get("CASCADEDLP_HOME", Path.home() / ".cascadedlp"))


@dataclass
class GateConfig:
    home: Path = field(default_factory=default_home)
    model: str | None = "qwen3.5:9b"      # None이면 규칙만 (LLM 없이)
    link: bool = True                     # 교차 표기 연결 사용
    allowed_roots: list[str] = field(default_factory=list)  # restrict_paths일 때 읽기·쓰기 허용 폴더
    projects: dict[str, list[str]] = field(default_factory=dict)  # {프로젝트: [폴더, ...]} — 폴더 아래 파일에 그 용어집 적용

    @classmethod
    def load(cls, home: Path | None = None) -> "GateConfig":
        """~/.cascadedlp/config.json 을 읽는다. 없으면 기본값으로 만들어 둔다.
        기본 허용 범위 = 사용자 폴더 전체(넓은 울타리). 경로는 대화에서 그때그때 지정하고,
        민감 폴더(DENIED_UNDER_HOME, 가명 맵 폴더)는 설정과 관계없이 항상 막는다."""
        home = Path(home) if home else default_home()
        path = home / "config.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"model": "qwen3.5:9b", "link": True, "allowed_roots": [str(Path.home())], "projects": {}}
            home.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return cls(home=home, model=data.get("model"), link=data.get("link", True),
                   allowed_roots=data.get("allowed_roots", []), projects=data.get("projects", {}))


@dataclass
class MaskResult:
    masked_text: str
    job_id: str
    counts: dict[str, int]      # 유형별 가명화 개수 (원래 값은 없음)
    seconds: float
    project: str | None = None
    blocked: bool = False       # L3(외부 금지) 용어가 있어 클라우드용 텍스트를 만들지 않음
    notice: str = ""


class PathNotAllowed(PermissionError):
    pass


_PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}")


# 허용 범위 안이라도 항상 막는 폴더 (사용자 폴더 기준). 가명 맵 폴더(cfg.home)도 항상 막힌다.
DENIED_UNDER_HOME = [".ssh", ".aws", ".gnupg", ".claude", "AppData", ".config", ".docker", ".kube"]


class Gate:
    def __init__(self, config: GateConfig | None = None, restrict_paths: bool = False):
        self.cfg = config or GateConfig.load()
        self.restrict_paths = restrict_paths
        self.map_path = self.cfg.home / "default.map.json"
        self.restore_dir = self.cfg.home / "restore"

    # ── 경로 검사 ──────────────────────────────────────────
    def _check(self, path: str | Path) -> Path:
        p = Path(path).resolve()
        if not self.restrict_paths:
            return p
        denied = [Path(self.cfg.home).resolve()] + [(Path.home() / d).resolve() for d in DENIED_UNDER_HOME]
        for d in denied:
            if p.is_relative_to(d):
                raise PathNotAllowed(f"항상 막는 폴더입니다(가명 맵·자격 증명·설정): {d}")
        for root in self.cfg.allowed_roots:
            if p.is_relative_to(Path(root).resolve()):
                return p
        raise PathNotAllowed(f"허용 폴더 밖의 경로입니다: {p}  (허용: {self.cfg.allowed_roots or '없음'} — "
                             f"{self.cfg.home / 'config.json'} 의 allowed_roots 에 추가)")

    # ── 프로젝트 용어집 ────────────────────────────────────
    def project_for(self, path: str | Path | None = None, project: str | None = None) -> str | None:
        """직접 지정이 우선, 없으면 config의 폴더 매핑으로 찾는다."""
        if project:
            if not _PROJECT_NAME.fullmatch(project):
                raise ValueError("프로젝트 이름은 영문·숫자·_·- 만")
            return project
        if path is not None:
            p = Path(path).resolve()
            for name, roots in self.cfg.projects.items():
                if any(p.is_relative_to(Path(r).resolve()) for r in roots):
                    return name
        return None

    def glossary(self, project: str | None) -> Glossary:
        if not project:
            return Glossary.empty()
        path = self.cfg.home / "projects" / project / "glossary.json"
        if not path.exists():
            raise FileNotFoundError(f"'{project}' 용어집이 없습니다: {path}")
        return Glossary.load(path)

    # ── 가명화 ────────────────────────────────────────────
    def mask_text(self, text: str, project: str | None = None) -> MaskResult:
        """로컬 프로그램용. (MCP에는 노출하지 않는다 — 원문이 호출자를 거치게 되므로)
        project를 주면 그 용어집의 레벨대로: L0 그대로 · L1 설명형 별칭 · L2 불투명 토큰 · L3 있으면 생성 거부."""
        t0 = time.perf_counter()
        gl = self.glossary(project)
        g_spans = gl.match(text)
        l3 = sorted({s.entity_id for s in g_spans if s.meta["level"] == 3})
        if l3:  # 외부 금지 용어가 있으면 클라우드용 텍스트를 만들지 않는다(무엇이 걸렸는지 용어 자체는 알리지 않음)
            return MaskResult("", "", {}, round(time.perf_counter() - t0, 2), project, blocked=True,
                              notice=f"L3(외부 금지) 항목 {len(l3)}종({', '.join(l3)})이 있어 클라우드용 텍스트를 만들지 않았습니다. "
                                     f"로컬 모델로 처리하거나 해당 부분을 빼고 다시 시도하세요.")
        pmap = PseudoMap(self.map_path)
        spans = rules.detect(text) + g_spans
        if self.cfg.model:
            for offset, chunk in chunks(text):  # 긴 문서는 나눠서 (LLM 컨텍스트 8K)
                spans += [Span(s.start + offset, s.end + offset, s.type, s.source)
                          for s in llm.detect(chunk, self.cfg.model)[0]]
        # L0(공개) 용어는 겹침 정리까지는 참여해서 LLM이 그 자리를 가리지 못하게 하고, 그다음 빼서 원문 그대로 둔다
        spans = [s for s in resolve(spans) if not (s.meta and s.meta["level"] == 0)]
        links = self._links(text, spans, pmap) if (self.cfg.model and self.cfg.link) else {}
        masked, restore = mask(text, spans, pmap, links)
        pmap.save()
        job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        self.restore_dir.mkdir(parents=True, exist_ok=True)
        (self.restore_dir / f"{job_id}.json").write_text(json.dumps(restore, ensure_ascii=False), encoding="utf-8")
        counts = dict(Counter(TOKEN_RE.match(r["token"]).group(1) for r in restore))
        return MaskResult(masked, job_id, counts, round(time.perf_counter() - t0, 2), project)

    def mask_file(self, path: str | Path, project: str | None = None) -> MaskResult:
        p = self._check(path)
        with open(p, encoding="utf-8", newline="") as f:  # 줄바꿈을 바꾸지 않아야 바이트 일치 복원
            return self.mask_text(f.read(), self.project_for(p, project))

    def _links(self, text, spans, pmap: PseudoMap) -> dict[str, list[str]]:
        """문서의 이름 + 맵에 이미 있는 이름을 로마자로 비교해 같은 사람 표기를 모은다 → {표기: [같은 사람 표기들]}"""
        doc = [text[s.start:s.end] for s in spans if s.type == "PERSON"]
        known = [x for e in pmap.entities.values() if e["type"] == "PERSON" for x in e["surfaces"]]
        surfaces = list(dict.fromkeys(doc + known))[:MAX_LINK_SURFACES]
        if len(surfaces) < 2 or not doc:
            return {}
        groups, _, _ = linking.link(surfaces, self.cfg.model, cache=pmap.romanized)
        links = {}
        for g in groups:
            names = [surfaces[i] for i in g]
            for n in names:
                links[n] = [m for m in names if m != n]
        return links

    # ── 복원 ──────────────────────────────────────────────
    def _restore_table(self, job_id: str) -> list[dict]:
        if not job_id.replace("-", "").isalnum():
            raise ValueError("잘못된 job_id")
        return json.loads((self.restore_dir / f"{job_id}.json").read_text(encoding="utf-8"))

    def unmask_text(self, answer: str, job_id: str) -> str:
        """로컬 프로그램용. (MCP에는 노출하지 않는다 — 복원문이 호출자에게 가게 되므로)"""
        return unmask(answer, self._restore_table(job_id), PseudoMap(self.map_path))

    def unmask_to_file(self, answer: str, job_id: str, out_path: str | Path, overwrite: bool = False) -> dict:
        """복원 결과를 파일로만 쓴다. 돌려주는 것은 경로와 개수뿐(내용 없음)."""
        out = self._check(out_path)
        if out.exists() and (self.restrict_paths or not overwrite):
            raise FileExistsError(f"이미 있는 파일은 덮어쓰지 않습니다: {out}")
        restored = self.unmask_text(answer, job_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(restored)
        n_tokens = len(TOKEN_RE.findall(answer))
        left = len(TOKEN_RE.findall(restored))  # 복원 못 한 토큰(맵에 없음)
        return {"path": str(out), "tokens_in_answer": n_tokens, "restored": n_tokens - left, "unresolved": left}

    # ── 조회 (원래 값 없이) ────────────────────────────────
    def entities(self) -> list[dict]:
        pmap = PseudoMap(self.map_path)
        return [{"token": t, "type": e["type"], "n_spellings": len(e["surfaces"])} for t, e in pmap.entities.items()]
