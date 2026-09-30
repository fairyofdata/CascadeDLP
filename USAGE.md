# CascadeDLP 사용법 (레이어)

외부 LLM에 보내기 **전에** 로컬에서 개인정보를 `[PERSON_001]` 같은 토큰으로 바꾸고, 답을 받은 뒤 **로컬 파일로** 되돌린다.
한·일·영 혼용 문서, 같은 사람의 다른 표기(한서윤 / ハン・ソユン / Seoyun Han)를 같은 토큰으로 묶는다.

## 구조
```
cascadedlp/gate.py        ← 중심 API (Gate)
  ├ cli.py             ← cascadedlp 명령 (내가 로컬에서 직접)
  └ mcp_server.py      ← cascadedlp-mcp (다른 Claude Code 대화에서 도구로)
~/.cascadedlp/            ← 가명 맵·복원표·설정 (절대 공유·커밋 금지)
  ├ config.json        {"model": "qwen3.5:9b", "link": true, "allowed_roots": [...]}
  ├ default.map.json   토큰 ↔ 원래 표기 + 로마자 캐시
  └ restore/<job>.json 작업별 복원표
```

## 🔴 경계 원칙
호출자(Claude Code 등)가 곧 외부 LLM이다.
- 원문은 **파일 경로로만** 넘긴다. 대화에 원문을 붙여 넣지 않는다.
- 호출자가 받는 것: 가명화된 텍스트, `job_id`, 유형별 개수.
- 복원 결과는 **로컬 파일로만** 쓴다. MCP 도구는 복원된 내용을 돌려주지 않는다.
- MCP는 `allowed_roots` 폴더 안만 읽고, 그 안에 **새 파일**로만 쓴다(덮어쓰기 금지).

## 1. CLI (로컬)
```powershell
cascadedlp mask 메모.txt -o 메모.masked.txt          # job id 출력
# 메모.masked.txt 를 외부 LLM에 보내고, 답을 답변.txt 로 저장
cascadedlp unmask 답변.txt --job <job_id> -o 답변.복원.txt
cascadedlp entities                                  # 토큰·유형·표기 수 (원래 값 없음)
cascadedlp --rules-only mask ...                     # LLM 없이 규칙만 (빠름)
```

## 2. MCP (다른 Claude Code 대화)
등록 (모든 프로젝트에서 쓰려면 user 범위):
```powershell
claude mcp add --scope user cascadedlp -- <저장소 경로>\.venv\Scripts\cascadedlp-mcp.exe
```
도구: `mask_file(path)`, `unmask_to_file(masked_text, job_id, out_path)`, `list_entities()`.
대화 예: "`D:\docs\회의록.txt` 를 cascadedlp로 가명화해서 요약해 줘. 복원본은 `D:\docs\회의록_요약.txt` 로."

## 3. Python API (로컬 프로그램 — 예: 외부 LLM API 호출 스크립트)
```python
from cascadedlp.gate import Gate
g = Gate()                                    # ~/.cascadedlp/config.json
r = g.mask_file("memo.txt")                   # 또는 g.mask_text(text) — 로컬 프로그램에서만
answer = call_external_llm(r.masked_text)     # 외부 API에는 가명화된 텍스트만
g.unmask_to_file(answer, r.job_id, "memo_answer.txt")
```

## 4. 프로젝트 용어집 (C1)
"이 프로젝트에서만 특별한 말"을 적어 두면 레벨대로 가린다. 파일: `~/.cascadedlp/projects/<프로젝트>/glossary.json`
(가명 맵보다 민감 — 저장소에 두지 말 것. 예시: [data/eval/c1_tessellane/glossary.json](data/eval/c1_tessellane/glossary.json))
```json
{"project": "myproj", "entries": [
  {"id": "COMPONENT_01", "kind": "COMPONENT", "level": 1, "status": "confirmed",
   "surfaces": ["Adaptive Scheduler", "조율기", "適応スケジューラ"], "alias": "작업 우선순위 스케줄러"}
]}
```
| level | 밖으로 나가는 모양 |
|---|---|
| 0 공개 | 그대로 |
| 1 내부 | `[COMPONENT_01: 작업 우선순위 스케줄러]` (이름만 숨김) |
| 2 핵심 | `[COMPONENT_01]` |
| 3 외부 금지 | 클라우드용 텍스트를 만들지 않음 → 로컬 모델로 |

- `status`가 `confirmed`가 아니면 최소 레벨 2로 처리.
- 표기 하나만 적어도 `adaptive_scheduler`, `AdaptiveScheduler`, `ADAPTIVE SCHEDULER` 같은 변형을 같이 잡는다. 일반명사 그대로(`スケジューラ`)는 적지 말고 한정어가 붙은 표기로.
- 적용할 프로젝트: `config.json`에 `"projects": {"myproj": ["D:\\work\\myproj"]}` (폴더 아래 파일에 자동), 또는 `--project myproj` / MCP `project` 인자.
```powershell
cascadedlp glossary-check myproj                         # 형식 점검
cascadedlp --project myproj mask 설계서.md -o 설계서.masked.md
```

## 성능 (합성 평가, qwen3.5:9b, RTX 3070) — 자세한 건 results/P4_summary_2026-09-30.md
- 탐지 F1 0.87~0.93, 문장당 약 2.8초. 교차 표기 연결 정밀도 1.0(다른 사람을 섞지 않음).
- 한계: 한자 이름 읽기(伊藤大翔), 공백으로만 붙은 2인 명단, 주소 경계. **민감한 문서는 가명화 결과를 눈으로 확인한 뒤 보낼 것.**
