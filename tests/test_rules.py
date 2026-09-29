"""P2 규칙 층: 한·일·영 형식 변형과 함정(잡으면 안 되는 숫자)."""
import pytest

from piigate.rules import detect
from piigate.spans import resolve


def found(text):
    return [(text[s.start:s.end], s.type) for s in resolve(detect(text))]


@pytest.mark.parametrize("text,expected", [
    ("연락처 010 4418 2093입니다", ("010 4418 2093", "PHONE")),
    ("フリーダイヤル 0120-555-731 まで", ("0120-555-731", "PHONE")),
    ("代表 (03) 5412-7788", ("(03) 5412-7788", "PHONE")),
    ("Fax: +81 6 6345 1122", ("+81 6 6345 1122", "PHONE")),
    ("여권번호 M12345678", ("M12345678", "ID_NUMBER")),
    ("Passport No. TK1234567 issued", ("TK1234567", "ID_NUMBER")),
    ("詳細はhttps://example.jp/a?id=1をご覧ください", ("https://example.jp/a?id=1", "URL")),
])
def test_formats(text, expected):
    assert expected in found(text)


@pytest.mark.parametrize("text", [
    "주문번호 1234-5678, 총 12,000원",
    "2026-09-29 13:30 に会議室Bで",
    "社員番号 A-20417、内線 3301。",
    "모델명 M12345678 재고 있음",  # 여권 키워드 없으면 잡지 않음
    "Version 3.14.7 was released",
])
def test_traps(text):
    assert found(text) == []
