# ADR-0012 가명 맵 위치: 사용자 홈 한 곳 (`~/.piigate`)

- 날짜: 2026-09-30 · 상태: 채택 (사용자 선택). 이전: 프로젝트 `maps/`

## 결정
- 맵·복원표·설정은 `%USERPROFILE%\.piigate\` (`PIIGATE_HOME`으로 바꿀 수 있음).
  - `config.json` `{"model", "link", "allowed_roots"}` — 없으면 기본값으로 생성.
  - `default.map.json`, `restore/<job_id>.json`.
- 어느 프로젝트·대화에서 불러도 **같은 맵** → "오늘 [PERSON_001]은 다음 주에도 [PERSON_001]"(차별점 3).
- 어떤 git 저장소에도 속하지 않아 실수로 커밋될 위험이 없다. 프로젝트 `.gitignore`의 `maps/`·`*.map.json`은 안전망으로 유지.

## 결과
- 단일 맵이라 프로젝트 간 분리가 필요하면 `PIIGATE_HOME`을 따로 지정.
- 맵 폴더는 MCP가 항상 읽지 못하게 막는다([ADR-0013](0013-path-policy.md)).
