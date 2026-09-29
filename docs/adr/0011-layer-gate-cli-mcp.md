# ADR-0011 레이어화: Gate API 중심 + CLI·MCP 어댑터, 경계 원칙

- 날짜: 2026-09-30 · 상태: 채택 (사용자 선택: Python API + MCP. 로컬 HTTP·외부 LLM 프록시는 보류)

## 맥락
다른 Claude Code 대화나 API식 호출에서 결합해 쓸 수 있는 레이어가 필요. **호출자(Claude Code 등)가 곧 외부 LLM**이라는 점이 설계의 핵심 제약.

## 결정
- `piigate/gate.py`의 `Gate`가 중심: `mask_file`, `mask_text`, `unmask_to_file`, `unmask_text`, `entities`.
- 어댑터: `piigate` CLI(로컬 사용자용, 경로 제한 없음), `piigate-mcp` MCP 서버(stdio, `restrict_paths=True`).
- `pyproject.toml`로 설치(`pip install -e .[mcp]`). MCP SDK 2.2(`mcp.server.mcpserver.MCPServer`, Python 3.14에서 동작).
- 🔴 경계 원칙 (MCP):
  1. 원문은 **파일 경로로만** 받는다 — 원문 텍스트를 인자로 받는 도구가 없다.
  2. 돌려주는 것은 **가명화된 텍스트·job_id·유형별 개수**뿐.
  3. 복원은 **로컬 파일로만** 쓰고 내용을 돌려주지 않는다(경로와 개수만). 기존 파일은 덮어쓰지 않는다.
  4. `list_entities`는 토큰·유형·표기 수만(원래 값 없음).
  5. `mask_text`/`unmask_text`는 로컬 프로그램(외부 API 호출 스크립트 등)용으로만 두고 MCP에 노출하지 않는다.
- 긴 문서는 1500자 단위로 나눠 탐지(LLM 컨텍스트 8K) — `gate.chunks`.
- 등록: `claude mcp add --scope user piigate -- <venv>\Scripts\piigate-mcp.exe` (2026-09-30 등록, `√ Connected`; 등록 전 `~/.claude.json.bak-piigate` 백업).

## 결과
- MCP E2E(실제 stdio 클라이언트, LLM 포함): 한 문서 안의 `한서윤`·`ハン・ソユン` → 같은 `[PERSON_001]`, 복원 바이트 일치, 허용 밖 경로 거부.
- md·json·txt 모두 처리, json은 가명화 후에도 유효.
- 한계: Claude가 가명화 텍스트를 받는 순간 그 텍스트(비개인정보 부분)는 외부로 나간 것이다. 민감 문서는 가명화 결과를 확인 후 사용(USAGE.md).
