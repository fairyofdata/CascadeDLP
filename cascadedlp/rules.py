"""P2 규칙 층: 형식이 있는 개인정보를 정규식으로 찾는다.

사람 이름·주소·회사명처럼 형식이 없는 것은 여기서 다루지 않는다(→ llm.py).
주민번호·마이넘버는 '형식'만 본다(체크섬 검사 안 함 — 합성 데이터는 체크섬이 안 맞는다).
"""
import re

from .spans import Span

# 숫자·하이픈이 앞뒤로 붙어 있으면 더 긴 숫자열의 일부이므로 제외한다.
_NB = r"(?<![\d\-])"   # not-before
_NA = r"(?![\d\-])"    # not-after

PATTERNS: list[tuple[str, re.Pattern]] = [
    # 비밀키 (C1): 서비스별 접두어가 있는 형식만. 개인 키 블록은 BEGIN~END 전체
    ("SECRET", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("SECRET", re.compile(r"(?<![A-Za-z0-9])(?:sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
                          r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}"
                          r"|hf_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_\-]{35})(?![A-Za-z0-9])")),
    # URL에 쓸 수 있는 ASCII 문자만 (일본어·한국어가 바로 붙어도 거기서 끊긴다)
    ("URL", re.compile(r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#@!$&'*+,;=%\[\]()]+")),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # 한국 주민등록번호: YYMMDD-[1-8]XXXXXX
    ("ID_NUMBER", re.compile(_NB + r"\d{6}-[1-8]\d{6}" + _NA)),
    # 일본 마이넘버: 12자리 (4-4-4 공백/하이픈 허용)
    ("ID_NUMBER", re.compile(r"(?<![\d])\d{4}[ \-]?\d{4}[ \-]?\d{4}(?![\d])")),
    # 국제 형식 (+81 일본, +82 한국)
    ("PHONE", re.compile(r"\+8[12][ \-]?\d{1,4}[ \-]?\d{2,4}[ \-]?\d{3,4}" + _NA)),
    # 한국 휴대폰 010-XXXX-XXXX (하이픈·공백 구분 또는 생략)
    ("PHONE", re.compile(_NB + r"01[016789][ \-]?\d{3,4}[ \-]?\d{4}" + _NA)),
    # 일본 프리다이얼·내비다이얼 0120-XXX-XXX, 0570-XXX-XXX
    ("PHONE", re.compile(_NB + r"0(?:120|570|800)-\d{3}-\d{3,4}" + _NA)),
    # 괄호 국번 (03) 5412-7788, (02) 123-4567
    ("PHONE", re.compile(r"\(0\d{1,4}\)\s?\d{1,4}-\d{4}" + _NA)),
    # 여권번호: 키워드가 앞에 있을 때만 (영문 1~2자 + 숫자 7~8자리는 흔한 코드와 겹친다). 스팬은 번호 부분(그룹 1)
    ("ID_NUMBER", re.compile(r"(?:여권\s*번호|여권|旅券番号|パスポート番号|[Pp]assport(?:\s*(?:[Nn]o\.?|number))?)"
                             r"\s*[:：]?\s*([A-Z]{1,2}\d{7,8})(?![\dA-Za-z])")),
    # 국내 고정전화·일본 휴대폰: 0으로 시작, 하이픈 필수 3덩어리 (예: 02-6953-1180, 086-255-0417, 090-3712-5584)
    ("PHONE", re.compile(_NB + r"0\d{1,4}-\d{1,4}-\d{4}" + _NA)),
    # 일본 우편번호 NNN-NNNN (〒 기호는 스팬에 넣지 않는다)
    ("POSTAL", re.compile(_NB + r"\d{3}-\d{4}" + _NA)),
    # 한국 5자리 우편번호: '우편번호'/'(우)' 뒤에서만 (단독 5자리는 너무 흔하다)
    ("POSTAL", re.compile(r"(?:(?<=우편번호 )|(?<=우편번호: )|(?<=\(우\) )|(?<=\(우\)))\d{5}(?!\d)")),
    # 미국 ZIP: 주 약어 2글자 뒤
    ("POSTAL", re.compile(r"(?<=\b[A-Z]{2} )\d{5}(?:-\d{4})?(?!\d)")),
]


def detect(text: str) -> list[Span]:
    """규칙으로 찾은 스팬(겹침 정리 전)."""
    spans = []
    for typ, pat in PATTERNS:
        for m in pat.finditer(text):
            g = 1 if pat.groups else 0  # 그룹이 있으면 그 부분만 스팬 (키워드 제외)
            start, end = m.start(g), m.end(g)
            if typ == "URL":  # 문장 끝 구두점은 URL이 아니다
                while end > start and text[end - 1] in ".,;:!?。、)]":
                    end -= 1
            spans.append(Span(start, end, typ, "rule"))
    return spans
