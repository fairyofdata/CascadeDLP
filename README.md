# LocalPIIGate

**외부 LLM 앞단의 로컬 개인정보 가명화 레이어 — 한·일·영 혼용 문서용**
*A local PII pseudonymization layer in front of external LLMs, built for mixed Korean / Japanese / English text.*

외부 LLM(Claude·GPT 등)에 텍스트를 보내기 **전에** 로컬에서 개인정보를 `[PERSON_001]` 같은 토큰으로 바꾸고, 답이 돌아오면 **로컬 파일로** 원래 값을 되돌립니다.

```
원문 ─▶ 탐지(규칙 + 로컬 LLM) ─▶ 가명화(일관·가역 토큰) ─▶ 외부 LLM ─▶ 복원(로컬 파일) ─▶ 결과
                                   └ (선택) 로컬 번역·요약으로 보낼 양 자체를 줄인다
```

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
- **가명 맵은 로컬에만.** `~/.piigate/` — 어떤 저장소에도 속하지 않는다.
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
git clone https://github.com/fairyofdata/LocalPIIGate.git
cd LocalPIIGate
.\setup.ps1        # venv · 의존성 · pip install -e .[mcp] · Ollama 모델 · 스모크 테스트
```
기본 모델은 `qwen3.5:9b`(약 6.6GB, 8GB VRAM에서 100% GPU). LLM 없이 규칙만 쓰려면 `--rules-only`.

## 사용법
자세한 건 [USAGE.md](USAGE.md).

**CLI**
```powershell
piigate mask memo.md -o memo.masked.md            # job id 출력
piigate unmask answer.md --job <job_id> -o answer.restored.md
piigate entities                                  # 토큰·유형·표기 수만 (원래 값 없음)
```

**MCP (Claude Code 등에서 도구로)**
```powershell
claude mcp add --scope user piigate -- <저장소 경로>\.venv\Scripts\piigate-mcp.exe
```
도구: `mask_file(path)` · `unmask_to_file(masked_text, job_id, out_path)` · `list_entities()`
경로·파일명·형식(md/json/txt/csv)은 대화에서 그때그때 지정. 기본 허용 범위는 사용자 폴더, 가명 맵 폴더·`.ssh`·`.claude`·`AppData` 등은 항상 차단, 덮어쓰기 금지([ADR-0013](docs/adr/0013-path-policy.md)).

**Python API**
```python
from piigate.gate import Gate
g = Gate()
r = g.mask_file("memo.txt")
answer = call_external_llm(r.masked_text)       # 외부에는 가명화된 텍스트만
g.unmask_to_file(answer, r.job_id, "memo_answer.txt")
```

## 구조
```
piigate/    spans · rules · llm · linking · pseudo · transform · gate(중심 API) · cli · mcp_server
tools/      build_eval · evaluate · relink · p5_eval · gliner_baseline   (측정 도구)
tests/      LLM 없이 도는 결정론 테스트 (라운드트립·규칙·후처리·경계·P5 보정)
data/eval/  합성 평가 세트 (v1 개발용, v2 홀드아웃) — 작성자·건수는 README
results/    측정 결과 (수치 + 합성 문장 오류 목록)
docs/adr/   설계 결정 기록 (ADR 0001–0014)
```

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
