# 평가 세트

**전부 합성 데이터.** 실존 인물·연락처·주소를 쓰지 않는다. 작성자와 건수를 버전마다 적는다.

| 파일 | 작성자 | 건수 | 날짜 |
|---|---|---|---|
| `eval_v1.jsonl` (원본 `eval_v1.src.tsv`) | 분석자 생성 (Claude, 합성) | 56문장 / 75스팬 | 2026-09-29 |

| `eval_v2.jsonl` (원본 `eval_v2.src.tsv`) | 분석자 생성 (Claude, 합성) | 58문장 / 77스팬 | 2026-09-30 |

| `c1_tessellane/docs_v1.jsonl` + `glossary.json` | 분석자 생성 (Claude, 합성 가상 프로젝트) | 35문장 / 36스팬, 용어집 9항목 | 2026-09-30 |

### C1 Tessellane (프로젝트 용어집)
- 가상 프로젝트 "Tessellane"의 설계서 문장(한·일·영). 용어 스팬 33 + 개인정보·비밀키 3.
- 용어집: L0 1 · L1 5(미확정 1 → 실효 L2) · L2 2 · L3 1, 고객사명 1.
- 표기 변형: snake_case·CamelCase·kebab·대문자·띄어쓰기. 함정 문장 10개(일반명사 '스케줄러'·'スケジューラ', adaptive scheduling, braid/solver, Atlassian 등).
- 용어집과 문장을 같은 쪽이 만들었으므로 매칭 수치는 결정론 동작 확인용.

### v2 구성 (홀드아웃)
- 목적: v1 오류를 보고 고친 코드의 과적합 확인. **코드를 고정한 채 한 번만 채점**(고정 시점 해시: `results/frozen_code_eval_v2.sha256`). v2를 보고 고친 뒤의 수치는 '튜닝 후'로 따로 표시한다.
- 유형별 스팬: PERSON 50, ADDRESS 8, PHONE 5, ORG 5, ID_NUMBER 3, EMAIL 2, POSTAL 2, URL 2
- 언어: ja 20, ko 18, en 14, 혼용 6 (한국어 문장 속 일본어 인용 등)
- 교차 표기 묶음 10개(Q1~Q10): 비슷한 이름(김민정/김민준), 같은 성 두 명(山本健太/山本健一 + 성만 있는 山本 = 연결하면 안 됨), 읽기가 여럿인 한자(大翔), 드문 성(오), 별칭 성(윤 Yoon/Yun), 서양 이름
- 형식 변형: 공백 구분 휴대폰, 프리다이얼(0120), 괄호 국번, 여권번호, 070, 공백으로만 구분된 이름 명단
- 함정 문장 4개(사번·내선·영수증 번호·방 번호·버전·날씨)

### v1 구성
- 유형별 스팬: PERSON 46, PHONE 7, ADDRESS 6, EMAIL 5, ORG 4, POSTAL 3, URL 2, ID_NUMBER 2
- 언어: ja 21, ko 18, en 13, 혼용(ja+en / ja+ko / ja+ko+en) 4
- 교차 표기 묶음 9개(P1~P9): 한글·한자·가나·로마자(성-이름/이름-성 순서 모두), 이름만/성만 약칭 포함
- PII 없는 함정 문장 5개(주문번호·날짜·버전 번호, 이름으로도 쓰이는 일반어 하늘/봄/春/桜)
- ⚠ 규칙 유형(PHONE·EMAIL 등)은 건수가 적어 P2 수치는 참고용. 필요하면 v2에서 보강.
- 메일·URL은 예약 도메인(`example.*`)만, 전화·주민번호·마이넘버는 가상 번호.

### 다시 만들기
원본은 인라인 마크업 `[[TYPE:ENTITY_ID|원문]]`으로 쓰고 변환한다(오프셋 수작업 방지):
```powershell
.\.venv\Scripts\python.exe tools\build_eval.py data\eval\eval_v1.src.tsv data\eval\eval_v1.jsonl
```

## 형식 (JSONL, 한 줄에 한 문장)
```json
{"id": "e001", "lang": "ja+ko", "text": "…",
 "spans": [{"start": 3, "end": 6, "type": "PERSON", "entity_id": "P1"}],
 "note": "교차 표기: P1 = 한글/가나 두 표기"}
```
- `start`/`end`는 파이썬 문자열 인덱스(코드 포인트).
- `entity_id`가 같으면 같은 사람·장소 — 교차 표기 연결 평가에 쓴다.
- 유형: PERSON, EMAIL, PHONE, POSTAL, ADDRESS, URL, ID_NUMBER, ORG
