# 인계 지시문

`DESIGN.md` 2026-08-18 전면 재작성 기준. **이 문서는 값을 복제하지 않는다** — 절 번호만 가리키고 실제 값은 `DESIGN.md`에서 읽는다.

> 이전 판은 골격·픽셀값을 여기에 캐시해 두었다가 `DESIGN.md`가 바뀌자 **정반대 지시를 하는 문서**가 됐다. 같은 실패를 반복하지 않기 위해 값을 적지 않는다.

---

## 0. 세션 시작 전

**작업 디렉터리를 `C:\dev\workops`로 열어야 한다.** 상위 폴더에서 열면 프로젝트 스킬 5개(`screen-design`·`ux-review`·`visual-review`·`data-contract`·`test-selection`)가 붙지 않는다.

```bash
cd C:/dev/workops && claude
```

먼저 읽을 것 — `DESIGN.md` 전문, `CLAUDE.md`(권위 계층), `AGENTS.md`(안전경계 정본).

---

## 1. 지금 상태 (2026-08-18)

**`DESIGN.md`는 새로 썼고, 코드는 한 줄도 안 바뀌었다.**

| 구분 | 상태 |
|---|---|
| 설계 기준 | §0~§6 확정 |
| 목업 | 평가 관리·근무표 편성·6유형 통일·모바일 3화면 (전부 정적 HTML, OS temp) |
| 코드 | **22개 화면 중 0개 변경** |
| 스킬 | 이름만 정리(`duty-*` 폐기). 내용은 §7.2-11 미해결 |
| 검증 | §5를 **한 번도 실행하지 않음** |

**막힌 것 3개** — 사내 기준이라 만들 수 없다.

1. 빈도×강도 기준표 실물 (축 눈금·라벨·25칸 매핑) — §7.2-1c
2. 오버라이드 허용 여부 — §7.2-1d
3. 근무형태 정본 (seed 6종 vs sample 10종) — §7.2-3

나머지 미해결 17개는 §7.2에 있다.

---

## 2. 새 화면을 만들 때

```
DESIGN.md를 읽고 시작해라.

1. 코드 상단에 §0 형식으로 세 상수를 먼저 쓴다.
   SCREEN_ARCHETYPE / SCREEN_DECISION / SCREEN_EVIDENCE
   결정 문장이 정확해야 골격이 맞게 나온다 — §0의 경고를 읽어라.

2. 그 유형의 §2 골격을 그대로 쓴다. 다른 유형의 규칙을 가져오지 마라.

3. 값은 §1 토큰에서만 고른다. 간격·타이포·색·밀도 전부. 새 값을 만들지 마라.
   예외는 §1.1의 데이터 밀도 예외뿐이고, 쓰면 이유를 주석에 남긴다.

4. §3 공통 패턴을 적용한다. 특히 §3.1(값 열은 하나)·§3.2(비활성 사유)·§3.6(어휘).

5. §4 금지 7개를 확인한다. 목록에 없는 것은 금지가 아니다.

6. 모바일 등급은 §3.4 표에서 확인한다. 미지원 화면이면 안내만 띄운다.

애매하면 구현 전에 물어라. 임의 판단으로 명세와 다르게 만들지 마라.
```

---

## 3. 기존 화면을 이관할 때

§7.1이 확정된 이관 계획이다. **순서가 있다.**

```
DESIGN.md §7.1을 읽고 시작해라.

첫 항목은 views/common/scaffold.py의 ARCHETYPES다. 이게 바뀌기 전에는
screen-design 스킬이 WORKLIST를 모른다(SKILL.md:16이 이 튜플을 값의 출처로 읽는다).

담당이 갈린다:
- 화면 골격 이관 → ui-feature
- 상태 전이 상수·DB 문서·migration → data-contract
  (글로벌 lee-mode PLAYBOOK이 ui-feature에 데이터 계약 변경을 금지한다)

migration은 AGENTS.md 승인 게이트 위에 Codex 교차검증 2단이 더 붙는다(§7.3-1).

깨지는 테스트는 3개로 확인돼 있다(§7.1 표). 나머지 32개는 회귀 기준선으로 쓴다.
```

---

## 4. 리뷰를 요청할 때

```
방금 구현한 화면을 다음으로 자체 점검하고, 위반 항목을 수정한 뒤 수정 내역만 요약해줘.

- §1 토큰 밖의 색·폰트 크기·간격이 있는가
- §2 해당 유형의 골격을 지켰는가
- §3.1 값 열이 하나인가
- §3.2 비활성 컨트롤에 사유가 화면에 쓰여 있는가
- §3.6 어휘가 한 낱말로 통일됐는가
- §4 금지 7개
- §5 측정: 대비율, 1366×768 겹침·잘림, 목록 행 높이 편차

정량 측정만으로 승인하지 마라. §5의 세 게이트(기계·측정·사람)를 구분해 보고해라.
```

---

## 5. ORCA 인계 (2026-08-18 세션 종료 시점)

`/lee-mode` Coordinator에게 그대로 붙여넣는다. **세션은 `C:\dev\workops`에서 열어야** 프로젝트 스킬 5종이 붙는다.

```
DESIGN.md 전문과 docs/WORKLOG.md 최상단 2026-08-18 항목을 먼저 읽어라.
설계 기준은 확정됐고, §7.1 이관의 1단계가 끝난 상태다.

[끝난 것]
- scaffold.py ARCHETYPES 교체(MASTER_DETAIL 폐기 → WORKLIST 신설, 순서도 §2와 일치)
- 7화면 SCREEN_ARCHETYPE 이관(판정 4 → WORKLIST, 내 것 조회 3 → READ_VIEW)
- views/master/style.py 제목 28px/설명 12px(§1.2) — 22화면 제목을 지배하던 한 줄
- 관련 테스트 갱신 + 되돌림 방지 검사 추가
- 회귀 기준선: scripts/test_*.py 35개 전부 통과(원격 쓰기 test_supabase_crud.py 제외)

[남은 것 — 이 순서로]
2단계 **완료(2026-08-18)** — `erp.select_list` 작성·노출·계약테스트(23 checks) 완료.
  시그니처: `select_list(key, items, *, selected=None, empty=..., height=None) -> str | None`
  items 원소: key(자연키·필수) / line1_left(제목) / line1_right(경과일) /
  line2_left(식별자·소속, 모노) / line2_right(분류) / accent(좌측 2px 상태색).
  반환은 "이번 run 에 새로 클릭된 키"뿐이고 **선택 상태 보관은 호출부(세션 키) 책임**이다.
  height 를 주면 목록이 자체 스크롤한다(상세와 독립 — §2 2열).
  선택 표시는 select_grid 와 같은 어휘(틴트 + 좌측 바 navy)로 맞췄다.
  select_grid 의 cellRenderer 차단(_SELECT_COL_CONFIG_ALLOWED)은 **뚫지 않았다** — 그 차단은
  옳고 요구가 그리드가 아니었을 뿐이라, my_schedule 의 components.v2 선례로 별도 컴포넌트를 만들었다.
  → 3단계를 바로 시작할 수 있다.

  (구 계획 원문) erp.select_list 신규 작성.
  WORKLIST 목록 행이 2줄 고정인데 st.button 은 label 이 inline 요소만 허용하고,
  select_grid 는 kit.py:653 _SELECT_COL_CONFIG_ALLOWED 가 cellRenderer 를 구조적으로
  차단한다. my_schedule.py:49 의 st.components.v2 패턴을 본떠 만든다.
  WORKLIST 4화면이 공유하므로 이게 없으면 3단계가 시작되지 않는다.

3단계(lee-mode, ui-feature Owner) near_miss_evaluate·near_miss_improvement 골격 이관.
  칩 스트립 + 전체폭 상세 → 상태 탭(st.segmented_control) + 2열.
  master_detail_frame(list_ratio=1, detail_ratio=2) — 기본값 1.5/1.0 은 60/40 이라 반대다.
  목록 독립 스크롤은 st.container(height=...).
  work_request_handle·lodging_manage 도 WORKLIST 지만 app.py 미라우팅 프로토타입이라 후순위.
  이관 시 test_near_miss_ui_gates.py:168 을 반대 방향으로 재작성한다
  (지금은 "구 골격 유지"를 지키는 과도기 검사다).
  끝나면 visual-qa 로 §5 측정 — 대비율, 1366×768 겹침·잘림, 목록 행 높이 편차.
  §5 는 **측정 게이트만 1회 실행됐다**(459f127: 대시보드·근무형태 관리·평가 관리를
  1366x768 / 1024x768 / 375x812 로 계측 — 제목 28px/600, 설명 12px, 아이콘 겹침 0,
  가로 스크롤 0, 렌더 예외 0). **기계 게이트와 사람 게이트는 여전히 미실행**이고,
  목록 행 높이 편차는 3단계 이후에야 측정 대상이 생긴다.
  이때 BACKLOG 의 공용 히트영역 30.1px(§1.4 compact 34px 미달) 건을 함께 실측한다.

4단계(직접) 확정값 적용: 등록 폼 라벨 열+하단 고정 바, 대시보드 역할 통합(_render_user 폐기),
  조회 컬럼 재구성, 제안등급 표시 4곳 제거, 어휘 통일(_STATUS_LABEL 단일 출처화가 선행),
  내 근무표·대시보드 히트영역 44px, 경과일 계산 신설(created_at 기준).

5단계(lee-mode, data-contract Owner) migration 3건을 한 번에 묶는다.
  frequency/severity 추가, review_started_by/at 추가, proposed_grade 제거 여부.
  백필은 설계하지 않는다(기존 아차사고 데이터는 전부 샘플·폐기 예정).
  NEAR_MISS_TRANSITIONS 에서 SUBMITTED→EVALUATED·SUBMITTED→REJECTED 제거 +
  docs/database.md:183 전이표·:91 "2단계 모델" 서술 동반 수정.
  AGENTS.md 승인 위에 lee-mode Codex 2단(DESIGN_DECISION+FINAL_INTEGRATED)이 더 붙는다.

[담당 경계]
화면 골격은 ui-feature, 상태 전이 상수·DB 문서·migration 은 data-contract 다.
글로벌 PLAYBOOK 이 ui-feature 에 데이터 계약 변경을 금지한다. 한 Owner 가 다 하지 않는다.

[반드시 알아야 할 함정]
- 미커밋 병행 작업은 **views/lodging_request.py(+271) 과 views/common/proto.py 두 파일뿐**이다.
  AGENTS.md 에 따라 보존한다. 커밋에 넣지 마라.
  (앞선 인계본은 views/workspace.py 와 scripts/test_sidebar_ui.py 도 병행 작업으로 적었으나
   **오분류다** — 실렌더 검증 세션의 산출물이고 459f127 로 이미 커밋됐다. 찾지 마라.)
  **단 proto.py 안에는 이 세션이 넣은 1줄 수정이 섞여 있다** — `MONO` 상수를
  `'"IBM Plex Mono", monospace'`(내부 큰따옴표)로 바꾼 것으로, 숙소예약·업무요청 3화면의
  신청번호 style 소실을 막는다. hunk 분리 스테이징이 CRLF 문제로 두 번 실패해 커밋하지
  않았다. **병행 작업 소유자가 proto.py 를 커밋할 때 이 줄이 함께 들어가야 한다** —
  빠지면 같은 시각 결함이 되살아난다.
- P1 결함 미수정: 평가 관리 보완요청 버튼이 활성인데 클릭하면 실패한다.
  활성 게이트는 006 프로브(near_miss_evaluate.py:171), 실행부는 007 프로브(db.py:2566).
- UI 서체 IBM Plex 를 Google Fonts CDN 에서 @import 한다(ui.py:37, 동봉 아님).
  외부망 차단 환경에서는 폴백되어 §1.2 가 지켜지지 않는다. 사내망 정책 확인 필요.
- 목업은 전부 정적 HTML 이었다. .orca/PLAYBOOK.md 는 실렌더 프로토타입을 기본으로 요구한다.

[아직 값이 임시인 것]
빈도×강도 격자의 눈금 라벨과 20칸 등급 배치. 구조(5×4·행렬법·중대성 우선 두 규칙)는
확정이므로 사내 위험성평가 기준표를 받으면 값만 교체한다. 화면·코드는 그대로다.

[완료된 조사 — 2026-08-18]
.claude 문서 감사 **완료·수정됨**. DESIGN.md 재편(§0 결정문장/§1 토큰/§2 화면유형/
§3 패턴/§4 금지/§5 검증)으로 사라진 §0.6·§0.3·§8 인용 15곳을 실제 섹션으로 교체했다:
  screen-design/SKILL.md 4 · screen-design/evals 2 · visual-review/SKILL.md 2 ·
  ui-feature.md 2 · ux-architect.md 5 · visual-qa.md 1.
숫자도 함께 갱신했다 — 구 "≥32×32px 단일 하한"은 폐기되고 §1.4 등급별
(cozy ≥44 / compact 34~38 / condensed 24~28, condensed 는 터치 조작 대상 아님)이 정본이다.
`grep -rn "§0\.[0-9]" .claude/agents .claude/skills` 잔여 0.

공용 코드 방해요소 조사 **완료**. 2026-08-14 검수에서 고친 4유형과 **같은 근본원인**의
잠복 3건을 찾았고 안전한 2건은 수정했다:
  (수정) `views/common/proto.py:32` MONO 상수가 작은따옴표를 품어 숙소예약·업무요청 3화면의
         신청번호 style 이 통째로 소실되고 있었다 — 아차사고 6화면만 고치고 이 공급원을
         빠뜨렸던 것.
  (수정) `views/master/style.py` — `.ms-chip` 만 12px 로 올리고 형제 라벨
         `.ms-ready`·`.cnt`·`.ctx`·`.lock`·`.ms-locked .s`·`.ms-empty .s`(9.8~10.4px)가
         하한 미달로 남아 있었다.
  (미수정·BACKLOG) 공용 버튼·입력 `min-height:2.15rem`=**30.1px** 가 §1.4 compact 34px 미달.
         이미 5곳이 개별 우회 중이라 공용 기본값이 틀렸다는 신호지만, 버튼 높이는 인접
         행·조건줄에 연쇄하므로 **3단계 visual-qa 측정과 함께** 처리하라.
새 선택자 오매치·flex min-width 누락은 추가 발견 없음(기존 수정이 해당 지점에서 충분).

`references/` 는 **깨진 참조가 아니다** — 이를 참조하는 것은 test-selection 뿐이고
`test-selection/references/test-map.md` 는 실재한다. screen-design 등은 references/ 를
인용하지 않으므로 디렉터리 부재가 결함이 아니다(구 인계 메모의 오기).
```

---

## 6. 이 문서를 고칠 때

- **값을 여기에 복제하지 않는다.** 픽셀·색·골격 상세는 `DESIGN.md`가 소유한다.
- 절 번호가 바뀌면 여기도 고친다. 지금 §번호는 2026-08-18 판 기준이다.
- `아차사고 관리.dc.html`은 **더 이상 레퍼런스가 아니다.** 새 `DESIGN.md`는 이 파일을 참조하지 않으며, §6 참조 구현은 실제 화면을 가리킨다.
