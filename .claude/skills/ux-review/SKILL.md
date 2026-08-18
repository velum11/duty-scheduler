---
name: ux-review
description: Usability (UX) review for workops ERP screens and screen designs in this repository — task flow, next-action clarity, form usability, error recovery, status feedback, and cognitive load, scored with a 0–4 severity scale. Preloaded on designated workops agents; the narrow workops-only wording is to minimize accidental selection elsewhere (it does not technically prevent it).
---

# Duty UX — 사용성 검토 (휴리스틱 평가)

workops 화면·설계안을 **사용성 관점**(사용자가 일을 얼마나 쉽게 끝내는가)으로 검토한다.
시각 품질(레이아웃·타이포·색)은 `visual-review`/`pixel-qa` 소관, 데이터 계약(저장·권한·정확성)은
contract-qa/data-contract 소관이다. 이 스킬은 **과업 흐름·발견성·피드백·오류 회복·인지 부하**만 다룬다.

구조 출처(보존 이식): wondelai/skills `ux-heuristics` 및 mastepanoski/claude-skills
`nielsen-heuristics-audit` — 둘 다 MIT License (Copyright (c) 2025 Wondel.ai sp. z o.o. /
Copyright (c) 2026 mastepanoski). Nielsen 10 휴리스틱·Krug 원리 구조를 차용하고
workops ERP 맥락으로 재작성했다. 라이선스 전문·허가 문구는 저장소 루트
`THIRD_PARTY_NOTICES.md` 참조.

## 핵심 원리 (Krug)

**"Don't Make Me Think"** — 모든 화면은 자명해야 한다. 무언가를 이해하는 데 생각이 필요하면
그것이 사용성 문제다. 클릭 수보다 **클릭당 인지 노력**이 중요하고, 사용자는 인내심이 아니라
**확신을 잃을 때** 이탈한다.

빠른 진단 3문 (화면마다):
1. 이 화면이 무엇인지 즉시 알 수 있는가?
2. 주된 행동(다음에 눌러야 할 것)이 명백한가?
3. 시스템이 지금 무슨 일이 일어나는지 보여주는가?

## 검토 축 (Nielsen 10 — ERP 튜닝)

각 축에서 "확인할 것"을 점검하고 위반을 심각도와 함께 기록한다.

1. **시스템 상태 가시성** — 저장 상태(dirty·저장됨·실패), 진행 중(스피너), 필터/조회 조건 상태,
   readiness(스키마 미준비) 배너, 상태 전이 결과 피드백.
2. **현실 세계와 일치** — 업무 용어(보고·평가·반려·보완요청·종결) 사용, 시스템 내부 용어
   (코드값·컬럼명) 미노출, 업무 순서와 화면 순서 일치.
3. **사용자 통제와 자유** — 취소·되돌리기 경로, 파괴적 행동 전 확인(2단계), 선택 해제 가능,
   편집 중 이탈 시 미저장 확인.
4. **일관성과 표준** — 같은 작업은 화면군 전체에서 같은 위치·같은 어휘·같은 컴포넌트
   (DESIGN.md §0 매니페스트·중립 키트 기준).
5. **오류 예방 + 폼 휴리스틱** — 잘못된 입력을 사전 차단(비활성·검증·조건부 렌더), 실수 유발
   배치 회피, 위험 행동은 멀리/구분. **폼 명시 점검**: 필수/선택 필드가 시각적으로 구분 표기
   되는가(`*` 등), 라벨이 무엇을 적어야 하는지 명확한가, 검증 실패 시 어느 필드가 왜인지
   즉시 아는가, 입력 순서가 업무 순서와 일치하는가.
6. **회상보다 재인** — 판단에 필요한 컨텍스트를 화면에 노출(접기 뒤에 숨기지 않음),
   선택지·상태를 보이게, 이전 화면 내용을 기억하게 강요하지 않음.
7. **유연성과 효율** — 반복 작업의 단축 경로(자동선택·기본값), 키보드 동선, 대량 작업 지원.
8. **미니멀리즘** — 과업과 무관한 정보 제거, 비활성 요소가 자리를 차지하지 않음,
   화면당 초점 1개.
9. **오류 인식·진단·회복** — 오류 메시지는 원인+다음 행동 제시(코드·traceback 노출 금지),
   실패해도 입력 보존, 부분 성공은 성공/실패 구분.
10. **도움말** — 필요한 지점에 인라인 힌트(help·placeholder·캡션), 별도 매뉴얼 의존 금지.

## 심각도 (0–4) — 반드시 근거 병기

| 등급 | 이름 | 정의 | 조치 |
|---|---|---|---|
| **4** | Catastrophic | 과업 완료 불가, 데이터 손실 유발, 보안·권한 문제 | 출시 전 즉시 수정 |
| **3** | Major | 핵심 과업에 심각한 지연·좌절·빈번한 문제 | 높은 우선순위 수정 |
| **2** | Minor | 간헐적 불편, 보조 기능 영향 | 중간 우선순위 |
| **1** | Cosmetic | 기능 영향 없음 | 여유 시 수정 |
| **0** | 문제 아님 | 사용성 이슈 아님 | 조치 불요 |

숫자만으로 근거 없는 정밀도를 만들지 않는다 — 각 finding에 **사용자 영향·발생 빈도·지속성·
증거 상태(실측/코드/추정)** 를 함께 기록한다. 이 0–4 척도는 UX 전용이다 —
`visual-review`의 High/Medium/Low(시각)와 **서로 변환하지 않는다**(UX 4=과업 차단·
데이터/보안, visual High=깨져 보임 — 의미가 다르다).

## 산출 형식 (Must/Should/Nice)

결과는 메시지/design brief 텍스트가 정본이다(사본을 `.orca/artifacts/<작업>/`에 남겨도 된다). "handoff"로 부르지 않는다 — Orca에서 handoff는 소유권 이전이다.
다음 구조로:

```
### Must Fix (심각도 4·3)
1. [문제] — H[축번호]: [축 이름]
   - 영향: [어느 핵심 과업이 어떻게 막히나] · 빈도: [상시/간헐] · 증거: [실측/코드/추정]
   - 수정: [구체 권고] · 공수: [낮음/중간/높음]
### Should Fix (심각도 2) …
### Nice to Have (심각도 1) …
```

## 경계·금지

- 평가 입력은 **설계 서술·코드·라이브 DOM 텍스트**를 기본으로 하고, 필요하면 스크린샷을
  보조 증거로 쓸 수 있다(`.orca/artifacts/`·temp에만 저장, 비밀 미포함).
- 색 대비 측정은 `pixel-qa` 소관(중복 금지). 시각 위계·"단정함"은 `visual-review` 소관.
- X/10 종합 점수 산출 금지 — 실렌더·측정 증거 없는 점수화는 프로젝트 룰 위반.
  심각도별 finding 목록이 산출의 전부다.
- 휴리스틱 검토는 실제 사용성 테스트가 아니다 — 긴 라벨·고밀도 데이터·empty/error/loading·
  권한별 상태를 포함한 **대표 과업 시나리오** 기준으로 점검하고, 확인 못 한 상태는
  "미검증"으로 정직하게 표기한다.

## History

<details>
<summary>정책 연혁</summary>

- 산출물 정책: 검토 결과의 사본과 보조 스크린샷을 `.orca/artifacts/<작업>/`(또는 OS temp)에
  둘 수 있다 — 비밀·개인정보·실데이터 미포함이 조건이며, 정본은 항상 메시지/design brief 텍스트다.
</details>
