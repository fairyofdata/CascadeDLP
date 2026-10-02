"""C2 용어집 부트스트랩: 프로젝트 문서에서 "이 프로젝트만의 말" 후보를 모아 사람이 검토할 md를 만든다.

    문서 폴더 → ① 후보 추출 → ② 걸러내기 → ③ 같은 대상 묶기 → ④ 검토 md → (사람이 체크) → apply → glossary.json

- 결정론: 코드 표기(snake_case·CamelCase), 영문 고유명(대문자 여러 단어), 표기 변형 정규화, 정의 패턴 A(B), 음차 비교 판정
- 로컬 LLM: 형식 없는 후보+설명, 사람 이름 탐지, 공개 기술·일반어 판정, 외래어 영어 철자 추정, 번역 관계 제안
- LLM이 제안한 번역 묶음은 '확인 필요' 줄에 따로 둔다 → 사람이 옮겨야만 반영
- 🔴 후보 목록은 '무엇이 핵심인가'의 초안이다. CLI 전용(MCP 미노출), 기본 저장 위치는 ~/.cascadedlp/projects/<프로젝트>/
"""
import datetime
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from . import llm
from .glossary import KINDS, _units, surface_pattern

BOOTSTRAP_PROMPT_VERSION = "b1"
DOC_SUFFIXES = {".md", ".txt"}

EXTRACT_SYSTEM = """You read internal project documents (Korean / Japanese / English, often mixed).
List the PROJECT-SPECIFIC names and jargon: internal project/product names and code names, component/service/module
names, internal algorithm or method names, internal terms and code words, customer/partner company names.
Do NOT list: widely known technologies or products (e.g. Kubernetes, PostgreSQL, Grafana, MQTT), generic words
(scheduler, cache, pipeline, dashboard), people's names, dates, numbers, file paths.
Copy each term EXACTLY as written in the text. Give kind (PROJECT, COMPONENT, ALGORITHM, TERM, ORG) and a short
description in Korean of what it is in this project (max 20 characters)."""
EXTRACT_SCHEMA = {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "object", "properties": {
    "text": {"type": "string"}, "kind": {"type": "string", "enum": ["PROJECT", "COMPONENT", "ALGORITHM", "TERM", "ORG"]},
    "description": {"type": "string"}}, "required": ["text", "kind", "description"]}}}, "required": ["terms"]}

PUBLIC_SYSTEM = """For each term (one per line), decide if it is a WIDELY KNOWN public technology, product, standard, or a
generic everyday/technical word (public=true), or a name that looks specific to one organization's project (public=false).
Answer for every term and copy the term exactly into "term"."""
PUBLIC_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "term": {"type": "string"}, "public": {"type": "boolean"}}, "required": ["term", "public"]}}}, "required": ["items"]}

TRANSLIT_SYSTEM = """For each Korean or Japanese term (one per line): if it is a phonetic transliteration of an English
word or name (a loanword), give the most likely original English spelling. If it is a native word or a translation (not
a transliteration), give an empty string. Answer for every term and copy the term exactly into "term"."""
TRANSLIT_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
    "term": {"type": "string"}, "english": {"type": "string"}}, "required": ["term", "english"]}}}, "required": ["items"]}
_LEADING_WORDS = {"the", "a", "an", "our", "see", "new", "old", "this", "that"}

TRANSLATE_SYSTEM = """You get English project terms (numbered E0, E1, ...) and Korean/Japanese project terms (numbered
K0, K1, ...), each with a short description. For each K term, if it clearly means the same thing as one E term
(a translation of it in this project), return that E number. If not sure, return -1. Different K terms may map to the
same E term only if they are the same concept in different languages."""
TRANSLATE_SCHEMA = {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object", "properties": {
    "k": {"type": "integer"}, "e": {"type": "integer"}}, "required": ["k", "e"]}}}, "required": ["pairs"]}

_CODE_IDENT = re.compile(r"\b(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b")
_TITLE = re.compile(r"\b[A-Z][a-z]+(?:[ \-](?:[A-Z][a-z]+|\d+))*[ \-][A-Z][a-z]+\b")
_LATIN_ONLY = re.compile(r"[A-Za-z0-9 _\-.]+")


def key(surface: str) -> str:
    """표기 변형을 하나로: 'Adaptive Scheduler' = 'adaptive_scheduler' = 'AdaptiveScheduler' → 'adaptivescheduler'"""
    return "".join(u.casefold() for u in _units(surface))


def is_latin(surface: str) -> bool:
    return bool(_LATIN_ONLY.fullmatch(surface))


def _sound(s: str) -> str:
    """음차 비교용: 소문자 알파벳만, 겹친 글자 하나로."""
    s = re.sub(r"[^a-z]", "", s.lower())
    return re.sub(r"(.)\1+", r"\1", s)


@dataclass
class Group:
    surfaces: Counter = field(default_factory=Counter)        # 표기 → 등장 횟수
    kinds: Counter = field(default_factory=Counter)
    descriptions: list = field(default_factory=list)
    docs: set = field(default_factory=set)
    sources: set = field(default_factory=set)                  # code / title / llm / 정의 패턴 / 음차
    suggested: dict = field(default_factory=dict)              # 확인 필요 표기 → 이유
    public: bool = False

    @property
    def title(self) -> str:
        return max(self.surfaces, key=lambda s: (self.surfaces[s], not is_latin(s), -len(s)))

    @property
    def kind(self) -> str:
        return self.kinds.most_common(1)[0][0] if self.kinds else "TERM"


@dataclass
class BootstrapResult:
    groups: list[Group]
    excluded: list[Group]
    n_docs: int
    llm_calls: int
    seconds: float


def clean_surface(surface: str) -> str:
    surface = surface.strip().strip("`*「」『』\"'")
    words = surface.split(" ")
    while len(words) > 2 and words[0].casefold() in _LEADING_WORDS:   # 'The Level-3 Pipeline' → 'Level-3 Pipeline'
        words.pop(0)
    return " ".join(words)


def term_candidates(text: str, model: str) -> dict[str, dict]:
    """한 문서에서 '프로젝트 용어처럼 생긴 말' 후보 → {key: {"surface", "kind", "desc", "llm"}}.
    라우터의 의심 항목 검사(C7)가 쓴다. 결정론 후보(코드 표기·영문 고유명)만 있는 것은 공개어 판정으로 걸러낸다."""
    found: dict[str, dict] = {}

    def add(surface, by_llm, kind="TERM", desc=""):
        surface = clean_surface(surface)
        if len(surface) < 2:
            return
        item = found.setdefault(key(surface), {"surface": surface, "kind": kind, "desc": desc, "llm": False})
        if by_llm:
            item.update(llm=True, kind=kind or item["kind"], desc=desc or item["desc"])

    for chunk in _chunks(text):
        try:
            terms = llm._chat(model, EXTRACT_SYSTEM, chunk, EXTRACT_SCHEMA).get("terms", [])
        except (json.JSONDecodeError, KeyError):
            terms = []
        for t in terms:
            if t.get("text") and t["text"] in chunk:
                add(t["text"], True, t.get("kind") if t.get("kind") in KINDS else "TERM", t.get("description", ""))
    for m in list(_CODE_IDENT.finditer(text)) + list(_TITLE.finditer(text)):
        add(m.group(0), False)

    det_only = {it["surface"]: k for k, it in found.items() if not it["llm"]}
    names = list(det_only)
    for i in range(0, len(names), 20):
        batch = names[i:i + 20]
        try:
            items = llm._chat(model, PUBLIC_SYSTEM, "\n".join(batch), PUBLIC_SCHEMA).get("items", [])
        except (json.JSONDecodeError, KeyError):
            items = []
        for it in items:
            k = det_only.get(it.get("term", "").strip())
            if k and it.get("public"):
                found.pop(k, None)
    return found


def read_docs(folder: str | Path) -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8"))
            for p in sorted(Path(folder).rglob("*")) if p.is_file() and p.suffix.lower() in DOC_SUFFIXES]


def _chunks(text: str, limit: int = 1500) -> list[str]:
    from .gate import chunks
    return [c for _, c in chunks(text, limit)]


def bootstrap(folder: str | Path, model: str) -> BootstrapResult:
    import time
    t0 = time.perf_counter()
    docs = read_docs(folder)
    calls = 0
    found: dict[str, Group] = {}          # key → Group
    person_keys: set[str] = set()

    def add(surface, source, doc, kind=None, desc=None):
        surface = surface.strip().strip("`*「」『』\"'")
        words = surface.split(" ")
        while len(words) > 2 and words[0].casefold() in _LEADING_WORDS:   # 'The Level-3 Pipeline' → 'Level-3 Pipeline'
            words.pop(0)
        surface = " ".join(words)
        if len(surface) < 2 or key(surface) in person_keys:
            return
        g = found.setdefault(key(surface), Group())
        g.surfaces[surface] += 0
        g.sources.add(source)
        g.docs.add(doc)
        if kind in KINDS:
            g.kinds[kind] += 1
        if desc:
            g.descriptions.append(desc.strip())

    # ① 후보 추출
    for name, text in docs:
        for chunk in _chunks(text):
            spans, _ = llm.detect(chunk, model)            # 사람 이름 걸러내기용 (기존 탐지 재사용)
            calls += 1
            person_keys |= {key(chunk[s.start:s.end]) for s in spans if s.type == "PERSON"}
            try:
                terms = llm._chat(model, EXTRACT_SYSTEM, chunk, EXTRACT_SCHEMA).get("terms", [])
            except (json.JSONDecodeError, KeyError):
                terms = []
            calls += 1
            for t in terms:
                if t.get("text") and t["text"] in chunk:     # 원문에 없는 문자열(환각)은 버림
                    add(t["text"], "llm", name, t.get("kind"), t.get("description"))
        for m in _CODE_IDENT.finditer(text):
            add(m.group(0), "code", name)
        for m in _TITLE.finditer(text):
            add(m.group(0), "title", name)
    for k in person_keys:                                    # 늦게 알게 된 사람 이름도 제거
        found.pop(k, None)

    # 등장 횟수·문서 수 (정규화된 표기 패턴으로 다시 센다)
    for g in found.values():
        g.docs = set()
        for s in list(g.surfaces):
            pat = re.compile(surface_pattern(s), re.IGNORECASE)
            for name, text in docs:
                n = len(pat.findall(text))
                if n:
                    g.surfaces[s] = max(g.surfaces[s], 0) + n
                    g.docs.add(name)
    groups = [g for g in found.values() if sum(g.surfaces.values()) > 0]

    # ② 공개 기술·일반어 판정 (LLM, 20개씩)
    for i in range(0, len(groups), 20):
        batch = {g.title: g for g in groups[i:i + 20]}   # 번호가 아니라 용어 자체로 답을 맞춘다(번호 어긋남 방지)
        try:
            items = llm._chat(model, PUBLIC_SYSTEM, "\n".join(batch), PUBLIC_SCHEMA).get("items", [])
        except (json.JSONDecodeError, KeyError):
            items = []
        calls += 1
        for it in items:
            g = batch.get(it.get("term", "").strip())
            if g and it.get("public"):
                g.public = True

    # 추출 LLM이 이미 '공개 기술은 빼라'는 지시로 낸 후보는 제외하지 않고 표시만 한다(조율기처럼 일반어처럼 생긴
    # 프로젝트 용어를 놓치지 않게). 코드·영문 고유명 형태로만 잡힌 후보만 공개 판정으로 제외한다.
    kept = [g for g in groups if not (g.public and "llm" not in g.sources)]
    excluded = [g for g in groups if g.public and "llm" not in g.sources]
    for g in kept:
        if g.public:
            g.sources.add("공개어일 수 있음")

    # ③ 같은 대상 묶기
    parent = list(range(len(kept)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b, why):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra
            kept[ra].sources.add(why)

    surf_index = {s: i for i, g in enumerate(kept) for s in g.surfaces}
    # (a) 정의 패턴: A(B) / A（B） / A (B)
    for _, text in docs:
        for s, i in surf_index.items():
            for m in re.finditer(re.escape(s) + r"\s?[(（]([^()（）\n]{2,40})[)）]", text):
                inner = m.group(1).strip()
                j = surf_index.get(inner)
                if j is None:
                    j = next((surf_index[x] for x in surf_index if key(x) == key(inner)), None)
                if j is not None and j != i:
                    union(i, j, "정의 패턴")
    # (b) 음차: 한·일 표기의 영어 철자 추정(LLM) → 영문 후보와 발음 비교(코드)
    non_latin = [i for i, g in enumerate(kept) if not any(is_latin(s) for s in g.surfaces)]
    latin = [i for i, g in enumerate(kept) if any(is_latin(s) for s in g.surfaces)]
    for b in range(0, len(non_latin), 25):
        batch = {kept[i].title: i for i in non_latin[b:b + 25]}
        try:
            items = llm._chat(model, TRANSLIT_SYSTEM, "\n".join(batch), TRANSLIT_SCHEMA).get("items", [])
        except (json.JSONDecodeError, KeyError):
            items = []
        calls += 1
        for it in items:
            i, eng = batch.get(it.get("term", "").strip()), _sound(it.get("english", ""))
            if i is None or len(eng) < 3:
                continue
            for j in latin:
                if any(SequenceMatcher(None, eng, _sound(s)).ratio() >= 0.85 for s in kept[j].surfaces if is_latin(s)):
                    union(j, i, "음차")
                    break
    # (c) 번역 관계: LLM 제안 → '확인 필요'로만 표시 (묶지 않음)
    roots = sorted({root(i) for i in range(len(kept))})
    e_roots = [r for r in roots if any(is_latin(s) for i in range(len(kept)) if root(i) == r for s in kept[i].surfaces)]
    k_roots = [r for r in roots if r not in e_roots]
    if e_roots and k_roots:
        def desc(r):
            ds = [d for i in range(len(kept)) if root(i) == r for d in kept[i].descriptions]
            return ds[0] if ds else ""
        user = ("\n".join(f"E{n}: {kept[r].title} — {desc(r)}" for n, r in enumerate(e_roots)) + "\n\n" +
                "\n".join(f"K{n}: {kept[r].title} — {desc(r)}" for n, r in enumerate(k_roots)))
        try:
            pairs = llm._chat(model, TRANSLATE_SYSTEM, user, TRANSLATE_SCHEMA).get("pairs", [])
        except (json.JSONDecodeError, KeyError):
            pairs = []
        calls += 1
        for p in pairs:
            k, e = p.get("k", -1), p.get("e", -1)
            if 0 <= k < len(k_roots) and 0 <= e < len(e_roots):
                target, src = kept[e_roots[e]], k_roots[k]
                for i in range(len(kept)):
                    if root(i) == src:
                        for s in kept[i].surfaces:
                            target.suggested[s] = "번역 관계(LLM 제안)"

    merged: dict[int, Group] = {}
    for i, g in enumerate(kept):
        r = root(i)
        if r not in merged:
            merged[r] = Group()
        m = merged[r]
        m.surfaces.update(g.surfaces)
        m.kinds.update(g.kinds)
        m.descriptions += g.descriptions
        m.docs |= g.docs
        m.sources |= g.sources
        m.suggested.update(g.suggested)
    # 한 문서에만 나온 긴 변형이 다른 후보를 포함하면('도크 펄스 에이전트' ⊃ '도크 펄스') 따로 세우지 않고 확인 필요로 붙인다
    groups_list = list(merged.values())
    for g in list(groups_list):
        if len(g.docs) > 1:
            continue
        for h in groups_list:
            if h is g or sum(h.surfaces.values()) <= sum(g.surfaces.values()):
                continue
            if any(key(s) != key(t) and key(t) in key(s) for s in g.surfaces for t in h.surfaces):
                for s in g.surfaces:
                    h.suggested[s] = "더 긴 변형(일반어가 붙었을 수 있음)"
                groups_list.remove(g)
                break
    final = sorted(groups_list, key=lambda g: (-len(g.docs), -sum(g.surfaces.values())))
    # 확인 필요 표기가 다른 후보의 본 표기로도 있으면, 그 후보는 목록에 그대로 둔다(사람이 합치거나 따로 채택)
    return BootstrapResult(final, excluded, len(docs), calls, round(time.perf_counter() - t0, 1))


# ── 검토 md ────────────────────────────────────────────
def render_review(res: BootstrapResult, project: str) -> str:
    lines = [f"# 용어집 후보 — {project}",
             f"생성 {datetime.date.today().isoformat()} · 문서 {res.n_docs}개 · 후보 {len(res.groups)}개 · "
             f"LLM 호출 {res.llm_calls}회 · {res.seconds}s · {BOOTSTRAP_PROMPT_VERSION}",
             "",
             "> ⚠ 이 파일은 '무엇이 이 프로젝트의 핵심인가'의 초안이다. 공유·커밋·외부 LLM 전송 금지.",
             "> 사용법: 채택할 항목의 `[ ]`를 `[x]`로. `kind`·`level`(0 공개 · 1 설명만 · 2 토큰 · 3 외부 금지)·`설명`·`표기`를 고쳐도 된다.",
             "> `확인 필요` 줄의 표기는 **`표기` 줄로 옮겨야만** 반영된다. 틀린 표기는 지운다.",
             f"> 끝나면: `cascadedlp --project {project} apply-review <이 파일>`",
             ""]
    for n, g in enumerate(res.groups, 1):
        desc = next((d for d in g.descriptions if d), "")
        lines += [f"## [ ] C{n:03d} · {g.title}",
                  f"- kind: {g.kind}",
                  "- level: 2",
                  f"- 설명: {desc}",
                  f"- 표기: {' | '.join(sorted(g.surfaces, key=lambda s: -g.surfaces[s]))}"]
        extra = [s for s in g.suggested if s not in g.surfaces]
        if extra:
            lines.append(f"- 확인 필요: {' | '.join(extra)}   ← {g.suggested[extra[0]]}")
        lines += [f"- 근거: {sum(g.surfaces.values())}회 · 문서 {len(g.docs)}개 · {', '.join(sorted(g.sources))}", ""]
    if res.excluded:
        lines += ["## 제외된 후보 (공개 기술·일반어로 판단 — 프로젝트 용어라면 [x])", ""]
        lines += [f"- [ ] {g.title}" for g in res.excluded]
    return "\n".join(lines) + "\n"


# ── apply ─────────────────────────────────────────────
_HEAD = re.compile(r"^## \[(x|X| )\] C\d+ · (.+)$")


def parse_review(md: str) -> list[dict]:
    items, cur, in_excluded = [], None, False
    for line in md.splitlines():
        if line.startswith("## 제외된 후보"):
            in_excluded, cur = True, None
            continue
        m = _HEAD.match(line)
        if m:
            cur = {"checked": m.group(1) in "xX", "title": m.group(2).strip(), "kind": "TERM", "level": 2,
                   "alias": "", "surfaces": []}
            items.append(cur)
            continue
        if in_excluded:
            m2 = re.match(r"^- \[(x|X)\] (.+)$", line)
            if m2:
                items.append({"checked": True, "title": m2.group(2).strip(), "kind": "TERM", "level": 2,
                              "alias": "", "surfaces": [m2.group(2).strip()]})
            continue
        if cur is None:
            continue
        m3 = re.match(r"^- (kind|level|설명|표기):\s*(.*)$", line)
        if m3:
            f, v = m3.groups()
            if f == "kind":
                cur["kind"] = v.strip().upper()
            elif f == "level":
                cur["level"] = int(v.strip()[:1]) if v.strip()[:1].isdigit() else 2
            elif f == "설명":
                cur["alias"] = v.strip()
            else:
                cur["surfaces"] = [s.strip() for s in v.split("|") if s.strip()]
    return [i for i in items if i["checked"] and i["surfaces"]]


def apply_review(md: str, glossary_path: str | Path, project: str) -> dict:
    """체크한 항목을 glossary.json에 confirmed로 반영. 이미 있는 표기와 겹치면 그 항목에 표기를 더한다."""
    path = Path(glossary_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"project": project, "entries": []}
    entries = data["entries"]
    owner = {s.casefold(): e for e in entries for s in e["surfaces"]}
    counters = defaultdict(int)
    for e in entries:
        k, _, num = e["id"].rpartition("_")
        counters[k] = max(counters[k], int(num) if num.isdigit() else 0)
    added = extended = 0
    for it in parse_review(md):
        kind = it["kind"] if it["kind"] in KINDS else "TERM"
        hit = next((owner[s.casefold()] for s in it["surfaces"] if s.casefold() in owner), None)
        if hit:
            new = [s for s in it["surfaces"] if s.casefold() not in owner]
            hit["surfaces"] += new
            owner.update({s.casefold(): hit for s in new})
            extended += bool(new)
            continue
        counters[kind] += 1
        e = {"id": f"{kind}_{counters[kind]:02d}", "kind": kind, "level": it["level"], "status": "confirmed",
             "surfaces": it["surfaces"], "alias": it["alias"]}
        entries.append(e)
        owner.update({s.casefold(): e for s in it["surfaces"]})
        added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"added": added, "extended": extended, "total": len(entries), "path": str(path)}
