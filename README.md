# CascadeDLP

**제한된 로컬 자원 + 클라우드 최상위 모델을 나눠 쓰는 하이브리드 캐스케이딩 DLP 레이어 — 한·일·영 혼용**
*A hybrid cascading DLP layer: a small local GPU decides what a frontier cloud model may see — for mixed Korean / Japanese / English work.*

GPU 한 장(RTX 3070 8GB)으로는 최상위 모델을 대신할 수 없고, 그렇다고 모든 것을 클라우드에 보낼 수도 없습니다.
CascadeDLP는 그 사이에서 **로컬 모델이 먼저 읽고, 무엇을 얼마나 가려서 어디로 보낼지** 정합니다.
목표는 많이 가리는 것이 아니라 **가장 적게 가리고도 보호 목적을 달성하는 것**입니다(정보 보존).

```
요청·문서·코드 ─▶ 로컬: 민감 엔티티 식별 → 같은 대상 연결 → 민감도(사람이 확정한 용어집)
                        │
      ┌─────────────────┼──────────────────┬──────────────┐
      ▼                 ▼                  ▼              ▼
 L0 클라우드 원문   L1–L2 클라우드 가림    L3 로컬 모델만     차단
                   (설명형 별칭·토큰)         (qwen3.5:9b)
                        │
                        ▼ 답 ─▶ 로컬 복원(파일) ─▶ 결과          + 감사 로그: 무엇이 나갔는가
```

> **현재 상태**: 1단계(개인정보 엔티티)와 C1(프로젝트 용어집) 구현·실측 완료. 코드로의 확장은 [로드맵](#로드맵). 방향 전환 배경은 [ADR-0015](docs/adr/0015-cascade-dlp-direction.md).

```text
Tessellane의 조율기는 Ripple Rank 점수를 쓰고 FastAPI 위에서 돈다.          (용어집: L1·L1·L2·L0)
        ↓
[PROJECT_01: 사내 물류 최적화 플랫폼]의 [COMPONENT_01: 작업 우선순위 스케줄러]는 [ALGORITHM_02] 점수를 쓰고 FastAPI 위에서 돈다.
```

### 1단계: 개인정보 엔티티 (구현됨)
외부 LLM에 보내기 **전에** 로컬에서 개인정보를 `[PERSON_001]` 같은 토큰으로 바꾸고, 답이 돌아오면 **로컬 파일로** 원래 값을 되돌립니다.

```text
昨日、한서윤さんと Tanaka Haruto から連絡。ハン・ソユンさんのメールは seoyun.han@example.com
        ↓
昨日、[PERSON_001]さんと [PERSON_002] から連絡。[PERSON_001]さんのメールは [EMAIL_001]
```

## 무엇이 다른가
이미 많은 PII 도구(Presidio, GLiNER …)가 있습니다. 여기서만 하는 것:

1. **한·일·영 혼용 문서** — 한 문장 안에 한글 이름, 가나 이름, 로마자가 섞여도 된다.
2. **교차 표기 연결** — `한서윤 / 韓瑞允 / ハン・ソユン / Seoyun Han` → 같은 `[PERSON_001]`.
3. **장기적으로 안정된 가역 가명화** — 오늘 `[PERSON_001]`이던 사람은 다음 주 다른 대화에서도 `[PERSON_001]`. 복원은 원문과 **바이트 단위로 일치**.
4. **기존 도구를 기준선으로 실측** — GLiNER는 공백 단위로 끊어 일본어 문장을 통째로 잡는 등 한·일 문서에 그대로 쓰기 어려웠다([ADR-0009](docs/adr/0009-gliner-baseline.md)).

## 설계 원칙
- **결정론이 먼저, 로컬 LLM은 형식 없는 것만.** 메일·전화·우편번호·URL·ID 형식은 정규식. LLM은 이름·주소·조직명 *후보 문자열*과 이름의 *로마자 발음*만 낸다. 위치 찾기, 토큰 부여, 같은 사람 판정, 복원은 전부 코드가 한다(환각은 원문에 없으므로 자동 폐기).
- **호출자는 외부 LLM이다.** MCP 도구는 원문을 인자로 받지 않고(파일 경로만), 복원 결과를 돌려주지 않는다(로컬 파일로만).
- **가명 맵은 로컬에만.** `~/.cascadedlp/` — 어떤 저장소에도 속하지 않는다.
- **개발·평가는 합성 데이터만.**

## 성능 (합성 평가, qwen3.5:9b, RTX 3070 8GB)
| | 개발 세트 eval_v1 | 홀드아웃 eval_v2 |
|---|---|---|
| 탐지 F1 (완전 일치) — 규칙만 | 0.404 | 0.230 |
| 탐지 F1 (완전 일치) — 규칙 + GLiNER | 0.593 | 0.526 |
| **탐지 F1 (완전 일치) — 규칙 + 로컬 LLM** | **0.873** | **0.875** |
| 교차 표기 연결 (묶음 완전 일치) | 7/9 | 7/10 |
| 연결 쌍 정밀도 (다른 사람을 섞지 않음) | 1.000 | 1.000 |
| 문장당 지연 | ~2.8s | ~2.8s |

- 홀드아웃은 코드를 고정한 채 1회 채점한 값([ADR-0010](docs/adr/0010-holdout-and-overfitting.md)). 이후 v2 오류를 보고 고친 버전은 v2 F1 0.933·연결 9/10(튜닝 후 수치).
- 로컬 번역 후 토큰 보존: **210/210** (망가지거나 새로 생긴 토큰 0) — [ADR-0014](docs/adr/0014-p5-local-transform.md).
- ⚠ 평가 세트는 모두 분석자(LLM) 생성 합성 문장이다. 절대값보다 방식·모델 간 상대 비교로 볼 것.

## 설치 (Windows, Python 3.12+, [Ollama](https://ollama.com))
```powershell
git clone https://github.com/fairyofdata/CascadeDLP.git
cd CascadeDLP
.\setup.ps1        # venv · 의존성 · pip install -e .[mcp] · Ollama 모델 · 스모크 테스트
```
기본 모델은 `qwen3.5:9b`(약 6.6GB, 8GB VRAM에서 100% GPU). LLM 없이 규칙만 쓰려면 `--rules-only`.

## 사용법
자세한 건 [USAGE.md](USAGE.md).

**CLI**
```powershell
cascadedlp mask memo.md -o memo.masked.md            # job id 출력
cascadedlp unmask answer.md --job <job_id> -o answer.restored.md
cascadedlp entities                                  # 토큰·유형·표기 수만 (원래 값 없음)
```

**MCP (Claude Code 등에서 도구로)**
```powershell
claude mcp add --scope user cascadedlp -- <저장소 경로>\.venv\Scripts\cascadedlp-mcp.exe
```
도구: `mask_file(path)` · `unmask_to_file(masked_text, job_id, out_path)` · `list_entities()`
경로·파일명·형식(md/json/txt/csv)은 대화에서 그때그때 지정. 기본 허용 범위는 사용자 폴더, 가명 맵 폴더·`.ssh`·`.claude`·`AppData` 등은 항상 차단, 덮어쓰기 금지([ADR-0013](docs/adr/0013-path-policy.md)).

**Python API**
```python
from cascadedlp.gate import Gate
g = Gate()
r = g.mask_file("memo.txt")
answer = call_external_llm(r.masked_text)       # 외부에는 가명화된 텍스트만
g.unmask_to_file(answer, r.job_id, "memo_answer.txt")
```

## 구조
```
cascadedlp/    spans · rules · llm · linking · pseudo · transform · gate(중심 API) · cli · mcp_server
tools/      build_eval · evaluate · relink · p5_eval · gliner_baseline   (측정 도구)
tests/      LLM 없이 도는 결정론 테스트 (라운드트립·규칙·후처리·경계·P5 보정)
data/eval/  합성 평가 세트 (v1 개발용, v2 홀드아웃) — 작성자·건수는 README
results/    측정 결과 (수치 + 합성 문장 오류 목록)
docs/adr/   설계 결정 기록 (ADR 0001–0014)
```

## 로드맵
문서(설계서·ADR·구조 설명) 먼저, 코드는 그다음([ADR-0015](docs/adr/0015-cascade-dlp-direction.md)).

| 단계 | 내용 | 상태 |
|---|---|---|
| P0–P5 | 개인정보 엔티티: 규칙 + 로컬 LLM 탐지, 교차 표기 연결, 가역 가명화, Gate/CLI/MCP, 로컬 번역·요약 | ✅ |
| C0 | 방향 재정의 (PII 마스커 → 캐스케이딩 DLP), 개명 | ✅ |
| C1 | 엔티티 확장(`PROJECT` `COMPONENT` `ALGORITHM` `TERM` `SECRET`) + 민감도 L0–L3 + 안전한 설명 + 프로젝트 용어집 ([ADR-0016](docs/adr/0016-project-glossary.md)) | ✅ |
| C2 | 용어집 부트스트랩: 로컬 LLM이 "이 프로젝트만의 말"과 다른 표기 묶음을 제안 → **사람이 민감도 확정** ([ADR-0017](docs/adr/0017-glossary-bootstrap.md), 홀드아웃 항목 10/10·잘못 합침 0) | ✅ |
| C3 | 정보 보존형 가림: 레벨별로 그대로 / 설명형 별칭 `[COMPONENT_01: 스케줄러]` / 토큰·요약 / 차단 | 레벨 ✅ · 요약 모드 미정 |
| C6 | 측정: 합성 가상 프로젝트에서 **효용(과제 성공) 대 유출(보호 용어가 나간 횟수)** — 1차: 용어 가림은 효용 유지, 용어 노출 0 ([ADR-0018](docs/adr/0018-utility-vs-leakage.md)). 다음: **의미 유출** | 진행 중 |
| C4 | 코드: L3 경로 읽기 금지 + 가린 미러 작업공간(핵심 함수는 시그니처·설명만) → 변경분 역매핑 | |
| C5 | 라우터(클라우드 원문 / 가림 / 로컬만 / 차단) + 감사 로그 | |

## 알려진 한계
- 한자 이름만으로는 읽기가 모호하다(伊藤大翔 → hiroto? daisho?) → 교차 연결 실패.
- 공백으로만 붙은 두 사람 이름(`정민호 김민준`)은 한 사람으로 합쳐진다.
- 주소 경계가 부정확하다(ADDRESS 완전 F1 0.44–0.57).
- 같은 표기의 동명이인은 구분하지 않는다.
- 가명화 결과(개인정보가 아닌 부분)는 외부로 나간다. **민감한 문서는 가명화 결과를 확인한 뒤 보낼 것.** 이 도구는 개인정보 보호를 돕는 보조 수단이며 완전한 탐지를 보장하지 않는다.

## 평가 데이터에 대해
`data/eval/`의 이름·주소·연락처는 모두 **지어낸 것**이다. 메일·URL은 예약 도메인(`example.com/.jp/.org`)만 쓴다. 전화·ID 번호는 형식만 맞춘 임의의 숫자로, 실제 번호와 일치한다면 우연이다.

## License
[MIT](LICENSE)
