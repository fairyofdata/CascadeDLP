# 용어집 후보 — tessellane
생성 2026-09-30 · 문서 5개 · 후보 16개 · LLM 호출 14회 · 91.7s · b1

> ⚠ 이 파일은 '무엇이 이 프로젝트의 핵심인가'의 초안이다. 공유·커밋·외부 LLM 전송 금지.
> 사용법: 채택할 항목의 `[ ]`를 `[x]`로. `kind`·`level`(0 공개 · 1 설명만 · 2 토큰 · 3 외부 금지)·`설명`·`표기`를 고쳐도 된다.
> `확인 필요` 줄의 표기는 **`표기` 줄로 옮겨야만** 반영된다. 틀린 표기는 지운다.
> 끝나면: `cascadedlp --project tessellane apply-review <이 파일>`

## [ ] C001 · AdaptiveScheduler
- kind: COMPONENT
- level: 2
- 설명: 작업 큐 우선순위 재계산 서비스
- 표기: Adaptive Scheduler | adaptive_scheduler | AdaptiveScheduler | 조율기 | 適応スケジューラ
- 근거: 31회 · 문서 5개 · code, llm, title, 공개어일 수 있음, 정의 패턴

## [ ] C002 · 도크 펄스
- kind: COMPONENT
- level: 2
- 설명: 창고 도크 상태 보고 에이전트
- 표기: 도크 펄스 | Dock Pulse | dock_pulse | ドックパルス
- 확인 필요: 도크 펄스 에이전트   ← 더 긴 변형(일반어가 붙었을 수 있음)
- 근거: 8회 · 문서 5개 · code, llm, title, 음차

## [ ] C003 · 골든 슬롯
- kind: TERM
- level: 2
- 설명: 오전 9~11 시 우선 배송 구간
- 표기: 골든 슬롯 | Golden Slot | ゴールデンスロット
- 근거: 5회 · 문서 5개 · llm, title, 음차

## [ ] C004 · Ledger Bridge
- kind: COMPONENT
- level: 2
- 설명: 정산 시스템과 배송 결과 매칭 모듈
- 표기: Ledger Bridge | ledger_bridge | 레저 브리지
- 확인 필요: 元帳ブリッジ   ← 번역 관계(LLM 제안)
- 근거: 13회 · 문서 4개 · code, llm, title, 정의 패턴

## [ ] C005 · Ripple Rank
- kind: ALGORITHM
- level: 2
- 설명: 우선순위 점수 산출 알고리즘
- 표기: Ripple Rank | ripple_rank | 리플 랭크 | リップルランク
- 근거: 12회 · 문서 4개 · code, llm, title, 음차, 정의 패턴

## [ ] C006 · 브레이드 솔버
- kind: COMPONENT
- level: 2
- 설명: 경로 생성을 위한 내부 수식 엔진
- 표기: 브레이드 솔버 | Braid Solver | braid_solver | ブレイドソルバー
- 근거: 9회 · 문서 4개 · code, llm, title, 음차

## [ ] C007 · 소라네 로지스틱스
- kind: ORG
- level: 2
- 설명: 고객사 또는 파트너 기업명
- 표기: 소라네 로지스틱스 | Sorane Logistics
- 확인 필요: ソラネ物流   ← 번역 관계(LLM 제안)
- 근거: 4회 · 문서 4개 · llm, title, 음차

## [ ] C008 · 테셀레인
- kind: PROJECT
- level: 2
- 설명: 창고 간 배송 순서 정하기 플랫폼
- 표기: 테셀레인 | Tessellane
- 근거: 5회 · 문서 3개 · llm, 정의 패턴

## [ ] C009 · 레벨3 파이프라인
- kind: COMPONENT
- level: 2
- 설명: 수집, 정제, 배정 3 단계 처리 흐름
- 표기: 레벨3 파이프라인 | Level-3 Pipeline
- 근거: 4회 · 문서 3개 · llm, title, 음차

## [ ] C010 · 나이트 하베스트
- kind: ALGORITHM
- level: 2
- 설명: 전날 주문 수집 배치 작업명
- 표기: 나이트 하베스트 | Night Harvest
- 확인 필요: 夜間ハーベスト   ← 번역 관계(LLM 제안)
- 근거: 3회 · 문서 3개 · llm, title, 음차

## [ ] C011 · TSL
- kind: TERM
- level: 2
- 설명: Tessellane 의 약칭
- 표기: TSL
- 근거: 2회 · 문서 2개 · llm, 공개어일 수 있음

## [ ] C012 · 元帳ブリッジ
- kind: COMPONENT
- level: 2
- 설명: 結果を受け取り精算データを突き合わせるモジュール
- 표기: 元帳ブリッジ
- 근거: 2회 · 문서 2개 · llm, 공개어일 수 있음

## [ ] C013 · テセレーン
- kind: PROJECT
- level: 2
- 설명: 本プロジェクトの名称
- 표기: テセレーン
- 근거: 1회 · 문서 1개 · llm

## [ ] C014 · L3パイプライン
- kind: COMPONENT
- level: 2
- 설명: 配車段階で呼ばれる内部処理フロー
- 표기: L3パイプライン
- 근거: 1회 · 문서 1개 · llm

## [ ] C015 · 夜間ハーベスト
- kind: ALGORITHM
- level: 2
- 설명: 毎日 2 時に実行されるバッチ処理
- 표기: 夜間ハーベスト
- 근거: 1회 · 문서 1개 · llm

## [ ] C016 · ソラネ物流
- kind: ORG
- level: 2
- 설명: 帳票定義を別途受注する顧客企業
- 표기: ソラネ物流
- 근거: 1회 · 문서 1개 · llm

## 제외된 후보 (공개 기술·일반어로 판단 — 프로젝트 용어라면 [x])

- [ ] GitHub
