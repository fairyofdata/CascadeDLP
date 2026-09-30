"""P4 v2 결정론 부분: 조각 병합·호칭 제거(llm.tidy), 로마자 비교 연결(linking.group). LLM 없이 검사."""
from cascadedlp.linking import group
from cascadedlp.llm import tidy
from cascadedlp.spans import Span


def surfaces(text, spans):
    return [(text[s.start:s.end], s.type) for s in spans]


def test_merge_split_names():
    t = "Please cc Seoyun Han and ハン・ソユン."
    got = tidy(t, [Span(10, 16, "PERSON", "llm"), Span(17, 20, "PERSON", "llm"),
                   Span(25, 27, "PERSON", "llm"), Span(28, 31, "PERSON", "llm")])
    assert surfaces(t, got) == [("Seoyun Han", "PERSON"), ("ハン・ソユン", "PERSON")]


def test_do_not_merge_across_words():
    t = "Minjae Park and Emily Carter"
    got = tidy(t, [Span(0, 11, "PERSON", "llm"), Span(16, 28, "PERSON", "llm")])
    assert len(got) == 2


def test_merge_address_pieces():
    t = "서울 마포구 도화동 5-3으로"
    pieces = [Span(0, 2, "ADDRESS"), Span(3, 6, "ADDRESS"), Span(7, 10, "ADDRESS"), Span(11, 14, "ADDRESS")]
    assert surfaces(t, tidy(t, pieces)) == [("서울 마포구 도화동 5-3", "ADDRESS")]


def test_name_list_not_merged():
    """공백으로만 구분된 3명 이상 명단은 한 사람으로 합치지 않는다."""
    t = "참석자: 정민호 김민준 오세린"
    got = tidy(t, [Span(5, 8, "PERSON"), Span(9, 12, "PERSON"), Span(13, 16, "PERSON")])
    assert [x for x, _ in surfaces(t, got)] == ["정민호", "김민준", "오세린"]


def test_numeric_only_llm_spans_dropped():
    """'04:30'을 주소로 가리는 과잉 가림 방지 (형식 있는 번호는 규칙 층이 맡음)."""
    t = "Dawn Sweep runs at 04:30 in Room 402"
    got = tidy(t, [Span(19, 24, "ADDRESS", "llm"), Span(0, 10, "ORG", "llm")])
    assert surfaces(t, got) == [("Dawn Sweep", "ORG")]


def test_strip_honorifics():
    t1 = "春ちゃんが来ます"
    assert surfaces(t1, tidy(t1, [Span(0, 4, "PERSON")])) == [("春", "PERSON")]
    t2 = "하늘이가 전화했어"
    assert surfaces(t2, tidy(t2, [Span(0, 3, "PERSON")])) == [("하늘", "PERSON")]


def R(f, g):
    return {"family": f, "given": g, "nationality": ""}


def as_sets(groups, names):
    return sorted(sorted(names[i] for i in g) for g in groups)


def test_group_cross_script():
    names = ["한서윤", "ハン・ソユン", "Seoyun Han", "ソユン", "박민재", "Bak Minjae", "Emily Carter", "Emily"]
    romans = [R("han", "seoyun"), R("han", "soyun"), R("seoyun", "han"),  # 3번째: LLM이 순서를 뒤집음
              R("", "soyun"), R("park", "minjae"), R("bak", "minjae"), R("carter", "emily"), R("", "emily")]
    assert as_sets(group(romans), names) == sorted([
        sorted(["한서윤", "ハン・ソユン", "Seoyun Han", "ソユン"]),
        sorted(["박민재", "Bak Minjae"]),
        sorted(["Emily Carter", "Emily"]),
    ])


def test_ambiguous_partial_stays_alone():
    """성만 있는 '山本'인데 야마모토가 두 명이면 연결하지 않는다."""
    romans = [R("yamamoto", "kenichi"), R("yamamoto", "yui"), R("yamamoto", "")]
    assert sorted(len(g) for g in group(romans)) == [1, 1, 1]


def test_swapped_slots_and_long_family_similarity():
    romans = [R("jeong", "minho"), R("", "chong minho"),          # LLM이 한 칸에 몰아 적음 + 정의 다른 로마자
              R("", "sophie martin"), R("", "sofie martan")]      # 긴 서양 성은 발음 유사도 허용
    assert sorted(len(g) for g in group(romans)) == [2, 2]


def test_short_family_needs_exact_match():
    """짧은 성은 유사도로 붙이지 않는다 (kim ≠ kin)."""
    assert len(group([R("kim", "yuna"), R("kin", "yuna")])) == 2


def test_different_given_names_not_merged():
    romans = [R("kim", "minjun"), R("kim", "seoyeon")]
    assert len(group(romans)) == 2
