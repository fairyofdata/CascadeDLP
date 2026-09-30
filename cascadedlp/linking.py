"""교차 표기 연결 v2: LLM은 표기마다 로마자 발음만 적고(llm.romanize), 같은 사람 판정은 여기서 코드가 한다.

판정 규칙
1. 성과 이름이 둘 다 있는 표기끼리: 성이 같고(별칭 표 적용) 이름 발음이 비슷하면 같은 사람.
   LLM이 성/이름 순서를 뒤바꿔 적은 경우도 한 번 더 본다.
2. 성만 / 이름만 있는 표기: 그 부분이 맞는 '성+이름' 사람이 딱 한 명일 때만 연결. 둘 이상이면 모호 → 따로 둔다.
"""
import re
import time
from difflib import SequenceMatcher

from . import llm

# 같은 성의 다른 로마자 표기
FAMILY_ALIASES = [
    {"park", "bak", "pak", "bahk"}, {"lee", "yi", "i", "rhee", "rhie"}, {"choi", "choe", "chwe", "che"},
    {"jung", "jeong", "chung", "cheong", "chong"}, {"kang", "gang"}, {"kim", "gim"}, {"yoon", "yun"},
    {"baek", "paek", "paik", "baik"}, {"shin", "sin"}, {"cho", "jo"},
]
_ALIAS = {name: min(group) for group in FAMILY_ALIASES for name in group}
SIMILAR = 0.8  # 이름 발음 유사도 기준 (0~1)


def loose(s: str) -> str:
    """발음 비교용으로 느슨하게: 기호 제거, 장음·모음 표기 차이 줄이기 (seoyun ≈ soyun, souta ≈ sota)."""
    s = re.sub(r"[^a-z]", "", s.lower())
    for a, b in (("eo", "o"), ("eu", "u"), ("ou", "o"), ("oo", "o"), ("uu", "u"), ("ei", "e"), ("ae", "e"),
                 ("ph", "f"), ("ck", "k"), ("c", "k")):
        s = s.replace(a, b)
    return s


def fam(s: str) -> str:
    s = re.sub(r"[^a-z]", "", s.lower())
    return _ALIAS.get(s, loose(s))


def similar(a: str, b: str) -> bool:
    a, b = loose(a), loose(b)
    return a == b or SequenceMatcher(None, a, b).ratio() >= SIMILAR


def same_family(a: str, b: str) -> bool:
    """성 비교: 별칭 표로 같으면 같음. 5자 이상 긴 성(서양·일본 성)은 발음 유사도도 허용 (martin ≈ martan)."""
    if fam(a) == fam(b):
        return True
    return min(len(loose(a)), len(loose(b))) >= 5 and similar(a, b)


def same_person(x: dict, y: dict) -> bool:
    """LLM이 성/이름 칸을 뒤바꿔 적는 일이 있어 두 순서를 모두 본다.
    짝지은 두 쌍 중 하나는 '성 비교'(별칭 표), 다른 하나는 '이름 비교'(발음 유사도)를 통과해야 한다."""
    for a1, a2 in ((x["family"], x["given"]), (x["given"], x["family"])):
        b1, b2 = y["family"], y["given"]
        if (same_family(a1, b1) and similar(a2, b2)) or (same_family(a2, b2) and similar(a1, b1)):
            return True
    return False


def _fix(r: dict) -> dict:
    """LLM이 한 칸에 전체 이름을 넣은 경우(family='', given='emily carter') 둘로 나눈다. 순서는 same_person이 양쪽 다 본다."""
    f, g = r.get("family", ""), r.get("given", "")
    whole = (f or g).split()
    if (not f or not g) and len(whole) == 2:
        return {**r, "given": whole[0], "family": whole[1]}
    return r


def group(romans: list[dict]) -> list[list[int]]:
    """로마자 발음 목록 → 같은 사람 묶음(인덱스). union-find."""
    romans = [_fix(r) for r in romans]
    parent = list(range(len(romans)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    full = [i for i, r in enumerate(romans) if r["family"] and r["given"]]
    for a in full:
        for b in full:
            if a < b and same_person(romans[a], romans[b]):
                parent[root(b)] = root(a)
    # 부분 표기: 정규화 후 '완전히 같은' 부분을 가진 사람(root)이 하나뿐일 때만.
    # (유사도로 붙이면 haru≈haruto, soyun≈doyun 처럼 짧은 이름이 엉뚱하게 붙는다)
    for i, r in enumerate(romans):
        if i in full or not (r["family"] or r["given"]):
            continue
        part = r["family"] or r["given"]
        hits = set()
        for j in full:
            fj, gj = romans[j]["family"], romans[j]["given"]
            if (r["family"] and fam(part) in (fam(fj), fam(gj))) or \
               (r["given"] and loose(part) in (loose(gj), loose(fj))):
                hits.add(root(j))
        if len(hits) == 1:
            parent[i] = hits.pop()
    groups: dict[int, list[int]] = {}
    for i in range(len(romans)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def link(surfaces: list[str], model: str, cache: dict | None = None) -> tuple[list[list[int]], float, list[dict]]:
    """표기 목록 → (묶음, 걸린 시간, 로마자 결과).
    cache({표기: 로마자})를 주면 이미 아는 표기는 LLM을 부르지 않고, 새로 부른 결과를 cache에 채운다."""
    t0 = time.perf_counter()
    romans = []
    for s in surfaces:
        if cache is not None and s in cache:
            romans.append(cache[s])
        else:
            r = llm.romanize(s, model)
            romans.append(r)
            if cache is not None:
                cache[s] = r
    return group(romans), time.perf_counter() - t0, romans
