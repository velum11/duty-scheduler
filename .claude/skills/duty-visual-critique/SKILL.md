---
name: duty-visual-critique
description: Qualitative visual design review for implemented duty-scheduler screens in this repository — layout, typography, colour, hierarchy, component consistency, interaction states, responsive quality — judged against "does this look professionally made or developer-made". Preloaded on the duty-scheduler visual-qa agent; complements pixel-qa (quantitative) and never replaces user sign-off. The narrow wording minimizes accidental selection elsewhere.
---

# Duty Visual Critique — 구현 후 시각 정성 검수

구현된 실화면을 **정성 시각 품질** 관점으로 검수한다. `pixel-qa`(정량: 지오메트리·겹침·잘림·대비
수치)와 **병행**하며 서로 대체하지 않는다. 데이터·기능·사용성 흐름은 소관 밖
(사용성은 `duty-ux`, 계약은 contract-qa).

구조 출처(보존 이식): jezweb/claude-skills `design-review` — MIT License
(Copyright (c) 2025 Jeremy Dawes (Jezweb)). 7축 루브릭·심각도 버킷·판정 기준을 차용하고
duty-scheduler ERP·DLP 맥락으로 재작성했다(원본의 파일 저장·배포 URL 절차는 제거).
라이선스 전문·허가 문구는 저장소 루트 `THIRD_PARTY_NOTICES.md` 참조.

## 핵심 판정 기준

> **"디자인 감각 있는 사람이 이 화면을 보고 '잘 만들었다'고 생각할까,
> '개발자가 만든 화면 같다'고 생각할까?"**

보조 판정 — **squint test**: 화면을 흐리게 봤을 때 가장 중요한 요소가 가장 먼저 눈에 들어오는가.
판정은 인상만으로 끝내지 않는다 — **DOM/computed-style 증거**(크기·간격·색·개수)를 동반해
근거를 남기고, 증거를 못 단 인상은 "주관 인상"으로 격하 표기한다.

## 7축 루브릭 (ERP 튜닝)

1. **레이아웃·간격** — 일관된 gap, 정렬선, 그리드 규율, 세로 리듬, 빈 공간이 의도인지 방치인지
   (§0.6 밀도 강제값 대조: 조건영역 ≤96px·상세 ≥600px·빈상태 ≤72px 등).
2. **타이포그래피** — 위계(제목/헤더/셀/배지 §2 토큰), 행 길이·행간, 크기 종수 과다 여부, 잘림.
3. **색·대비** — 의미 기반 색 사용(§4 상태 이중부호화), 색 일관성, 색 남용(신호 과다),
   대비 수치는 pixel-qa 결과 인용.
4. **시각 위계** — 주 행동이 지배적인가(squint test), 화면당 초점 1개, 그룹핑, 여백의 의도성.
5. **컴포넌트 일관성** — 버튼·카드·폼 입력·아이콘·radius·그림자가 화면군 전체에서 단일 어휘인가
   (radius 혼재·카드 남발 = 위반), 중립 키트 사용 여부.
6. **인터랙션 상태** — hover/focus/active/disabled 구분 가시, 로딩 표시, 선택 상태 이중부호화.
7. **반응형 품질** — baseline 1366 + 영향받는 보조 뷰포트, 히트 타깃(**USER·터치 44px,
   데스크톱 ERP 일반 인터랙션 타깃 32×32px** — DESIGN §0.6·§4), 그리드 내부 스크롤 처리.

원본 7축은 유지하되 색·대비 축의 dark-mode 체크는 비적용(본 제품 라이트 전용 출하).
**반(反)장식 교차 원칙(전 축 공통)**: hero·장식 카드·그라데이션·불필요 애니메이션·과대 여백·
실데이터 없는 장식 차트가 있으면 어느 축에서든 위반으로 기록한다(밀도·명료가 이 제품의 품질).

## 심각도 버킷

- **High** — "깨져 보이거나 비전문적으로 보인다" (겹침·오정렬·위계 붕괴·radius/스타일 혼재)
- **Medium** — "다듬어지지 않아 보인다" (어색한 간격·과대 컨트롤·일관성 흠)
- **Low** — "트집 수준" (미세 간격·보조 요소)

## 평가 입력 (DLP 준수)

- 1차: **라이브 DOM/computed-style 관찰**(Playwright, 기존 DOM QA 레시피) — 수치·구조 증거.
- 2차(조건부): **인메모리 vision** — 스크린샷 bytes를 **메모리에서만** 취득·판독한다.
  조건: sample/static 데이터 화면만 사용, 파일·temp·cache에 이미지 기록 0을 도구 수준에서
  확인, 보장 불가하면 vision을 포기하고 DOM-only로 강등 후 그 한계를 보고에 명시.
- 산출은 메시지/보고 텍스트만 — 스크린샷·이미지·HTML 리포트 파일 생성 금지(AGENTS.md DLP).

## 산출 형식

```
### 종합 인상 (1–2줄, 판정 기준 문장으로)
### High / Medium / Low findings
- [축N] 문제 — 증거(DOM 수치/vision 관찰) — 권고
### 잘된 점 (2–3개 — 유지할 것)
### Top 3 Fixes
```

X/10 점수화 금지. 최종 시각 승인은 항상 **사용자 실브라우저 sign-off**다 — 이 검수는 그
게이트를 대체하지 않고 앞서 거른다.
