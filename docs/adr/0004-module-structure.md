# ADR-0004 모듈 구조: 단계별 작은 파일

- 날짜: 2026-09-29 · 상태: 채택 (사용자 선택), 2026-09-30 `gate.py` 추가로 확장

## 결정
```
piigate/
  spans.py      Span + 겹침 정리(resolve)
  rules.py      P2 정규식
  llm.py        P4 Ollama 호출(detect, romanize) + 후처리(tidy), PROMPT_VERSION
  linking.py    교차 표기 판정(로마자 비교, union-find)
  pseudo.py     P3 가명 맵·mask·unmask
  transform.py  P5 번역·요약·토큰 보정
  gate.py       중심 API (ADR-0011)
  cli.py / mcp_server.py   Gate를 부르는 얇은 껍데기
tools/  build_eval, evaluate, relink, p5_eval, gliner_baseline (본체에 넣지 않는 측정 도구)
tests/  라운드트립·규칙·후처리·Gate 경계·P5 보정 (LLM 없이 도는 결정론 테스트만)
```
- 사용자가 코드를 "읽을 수 있지만 쓰는 건 약함" → 파일당 50~200줄, 한 파일 = 한 역할.

## 결과
- LLM 없이 도는 테스트 98개(2026-09-30). LLM이 필요한 검증은 `tools/`의 측정 스크립트로 분리.
