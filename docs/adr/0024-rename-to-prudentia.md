# 0024. 이름 변경: CascadeDLP → Prudentia

- 상태: 채택 (2026-11-24) · 사용자 결정

## 맥락
- 같은 사람이 만든 다른 도구(Concordia·Harmonia 등)와 이름 짓는 방식을 맞춘다. Prudentia는 라틴어 「분별」로, 무엇을 클라우드에 보일지 로컬이 정한다는 이 도구의 역할을 가리킨다.
- 평가 동결 해시(`results/frozen_code_*.sha256`)는 `cascadedlp/` 경로로 적혀 있다. 패키지 폴더를 바꾸면 지금 작업트리와는 맞지 않게 된다.

## 결정
- 패키지 `prudentia`, 명령 `prudentia`·`prudentia-mcp`, MCP 서버 이름 `prudentia`, 환경변수 `PRUDENTIA_HOME`, GitHub `fairyofdata/Prudentia`.
- 설정·맵 폴더 기본값은 `~/.prudentia`. **`~/.prudentia`가 없고 옛 `~/.cascadedlp`가 있으면 옛 폴더를 그대로 쓴다** — 가명 맵·복원표를 잃으면 되돌릴 수 없기 때문이다. 폴더를 옮기면 새 이름이 쓰인다.
- 개명 직전 커밋에 태그 `cascadedlp-final`을 단다. 그 커밋에서 `frozen_code_c7_holdout.sha256`은 15개 중 14개가 맞는다(`mcp_server.py`는 698fc2f의 등록 방식 변경, 측정 경로 아님). `frozen_code_c2_holdout.sha256`은 전과 같이 커밋 `a25623a`와 맞는다.
- `results/`와 ADR 0001–0023 본문은 당시 기록이라 옛 이름 그대로 둔다(ADR-0015가 `piigate`를 둔 것과 같다).

## 결과
- C7 수치를 같은 코드로 다시 재려면 `git checkout cascadedlp-final`. 지금 코드는 import 이름만 다르다.
- MCP 도구 이름이 `mcp__cascadedlp__*`에서 `mcp__prudentia__*`로 바뀐다. 설정을 바꾼 뒤 클라이언트를 다시 시작해야 한다.
- 폴더를 옮기면 편집 설치(`pip install -e .[mcp]`)를 다시 해야 한다.
- GitHub는 옛 레포 주소를 새 주소로 넘겨 준다.
