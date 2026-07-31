"""아차사고 등록 — 폼형(DESIGN.md §1-D) 단건 제출 폼(FORM_ENTRY).

신판 DESIGN.md §1-D "폼형" 골격으로 구현한다(색 리스킨이 아니라 구조 교체):

    01 · 기본 정보 / 02 · 상황 기술  — 모노 오버라인 + 헤어라인 구획, 필드 flex-wrap.
    우측: 필수항목 체크리스트 + 진행 바(좁아지면 본문 아래로 wrap). 하단 [제안서 제출](오렌지).

- 본문 아이콘 툴바 띠·카드 제거(§0 금지 3·5). §2~§4 값만(§0 금지 8).
- 03 · 사진 첨부 섹션(선택): st.file_uploader(다중) + st.camera_input(촬영, expander)로
  현장 사진을 첨부한다. **스테이징-후-첨부** 흐름이다 — db 사진 업로드 API 는 '이미 존재하는
  SUBMITTED 소유 보고서'를 요구하는데 등록 폼에는 제출 전까지 report_id 가 없으므로, 선택
  사진을 세션에 스테이징(선택 즉시 photo_storage 로 검증·압축)했다가 제출로 보고서가 생성된
  뒤 각 사진을 db.upload_near_miss_photo(new_id,...) 로 첨부한다. 업로더/카메라는 st.form 밖에
  배치한다(폼 위젯은 제출 전까지 반응하지 않아 썸네일·삭제 상호작용 불가 — §0.4 FORM_ENTRY
  예외). 사진은 선택 항목이라 필수 8필드·체크리스트에 미포함, 없어도 제출된다. '임시 저장'
  버튼은 현재 앱 미지원이라 추가하지 않는다.
- 체크리스트 진행 표시는 st.form 제약상 **렌더 시점(직전 rerun) 세션 값** 기준이다(폼 위젯은
  제출 전까지 세션에 커밋되지 않음) — 스크립트 해킹 없이 form 계약을 지킨 적응이다.

레퍼런스 골격: ``아차사고 관리.dc.html`` isForm 블록(630~735).

기능 계약(불변): 제출 검증·필수 8필드·저장 경로·성공 화면 흐름·st.form 제출 계약 전부 보존.
신원(신고자/사번/소속/created_by)은 위젯이 아니라 세션 사용자에서 서버측 확정(위조 방지).
U/M/A 공유 — USER 모바일에서 체크리스트가 본문 아래로 내려간다(≤900px). db.py 무수정.
"""
# DESIGN.md §1-D 폼형 — 단건 입력·제출.
SCREEN_ARCHETYPE = "FORM_ENTRY"

import uuid
from datetime import date
from html import escape

import streamlit as st

from modules import auth, db, photo_storage, ui
from views.common import erp
from views.common import scaffold
from views.master import PersistResult, banner, ledger_banner

_PAGE_ID = "near_miss_submit"
_DONE_KEY = "nm_submit_done"

# ── 사진 스테이징(제출 전 세션 보관 → 제출 성공 후 db API 로 첨부) ──
_STAGE_KEY = "nm_photo_stage"        # list[{"id","name","bytes","size"}] — 압축 JPEG + 원본 크기
_STAGE_SEEN_KEY = "nm_photo_seen"    # 이미 처리한 업로더/카메라 file_id 집합(중복 스테이징 방지)
_UP_KEY = "nm_f_photo_uploader"
_CAM_KEY = "nm_f_photo_camera"

# 업로드 상한(계약: 원본 ≤10MB/장). photo_storage.MAX_UPLOAD_BYTES 를 단일 출처로 삼되(읽기만),
# 위젯 인자(max_upload_size, MB)와 서버 config(maxUploadSize) 로 다층 차단한다.
_MAX_UPLOAD_BYTES = photo_storage.MAX_UPLOAD_BYTES
_MAX_UPLOAD_MB = max(1, _MAX_UPLOAD_BYTES // (1024 * 1024))
# 다중 선택 누적 상한 — 스테이징 원본 총량. 3장×10MB 여유를 두되 과대 메모리 적재를 막는다.
_STAGE_TOTAL_CAP_BYTES = 30 * 1024 * 1024
_STAGE_TOTAL_CAP_MB = _STAGE_TOTAL_CAP_BYTES // (1024 * 1024)

_FORM_WIDGET_KEYS = [
    "nm_f_work_name", "nm_f_incident_date", "nm_f_cause_code",
    "nm_f_cause_detail", "nm_f_work_content", "nm_f_incident_content",
    "nm_f_countermeasure", "nm_f_site_description",
]

_CAUSE_LABELS = {
    "JAM": "끼임", "FALL": "추락", "DROP": "낙하물", "HIT": "부딪힘·충돌",
    "SLIP": "미끄러짐·넘어짐", "BURN": "화상·고온", "PINCH": "협착", "ETC": "기타",
}

# 필수 8필드(라벨·세션키) — _validate 계약과 동일 집합. 체크리스트·진행 바가 이 목록에서 파생.
_REQUIRED = [
    ("작업명", "nm_f_work_name"),
    ("발생일", "nm_f_incident_date"),
    ("발생원인", "nm_f_cause_code"),
    ("발생원인 상세", "nm_f_cause_detail"),
    ("사고내용", "nm_f_incident_content"),
    ("작업내용", "nm_f_work_content"),
    ("작업현장 상황설명", "nm_f_site_description"),
    ("예방대책", "nm_f_countermeasure"),
]

# ── §2 팔레트 (팔레트 밖 색 금지 §0-8) ──
_INK = "#1c1a17"
_INK2 = "#4a453d"
# Codex P1: _WEAK/_FAINT 는 모두 읽는 작은 텍스트(오버라인·키 라벨·(선택)·힌트·안내)에 쓰이므로
# #6b665d(5.1:1↑)로 상향한다 — #8b857c·#a09a90 은 읽는 텍스트 금지.
_WEAK = "#6b665d"   # 읽는 보조 텍스트(구 #8b857c)
_FAINT = "#6b665d"  # 읽는 캡션·모노 오버라인(구 #a09a90)
_LINE = "#e6e2da"
_LINE_SEC = "#e0dbd2"
_LINE_HDR = "#cfc8bd"
_ACCENT = "#c2410c"
_ACCENT_TEXT = "#b4451a"
_MONO = "'IBM Plex Mono', monospace"

_FORM_CSS = f"""
<style>
/* st.form 기본 테두리 박스 제거 — §0-5 카드 금지(폼 전체를 감싸는 border+radius 금지).
   기능(폼 배치·제출 계약)은 불변, 시각 박스만 제거한다. */
[data-testid="stForm"] {{ border:none !important; background:transparent !important;
  padding:0 !important; }}
/* 신고자 정보 — 카드 아님(헤어라인만). REPORTER 오버라인 + 읽기전용 신원. */
.nm-reporter {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.4rem 1.4rem;
  padding:0 0 12px; border-bottom:1px solid {_LINE_SEC}; margin:2px 0 4px; }}
.nm-reporter .ov {{ font-family:{_MONO}; font-size:10px; letter-spacing:.14em; color:{_FAINT};
  flex:0 0 auto; }}
.nm-reporter .it {{ display:flex; gap:.4rem; align-items:baseline; font-size:13.5px; }}
.nm-reporter .k {{ color:{_WEAK}; }}
.nm-reporter .v {{ color:{_INK}; font-weight:600; }}
.nm-reporter .lock {{ margin-left:auto; font-size:12px; color:{_FAINT}; white-space:nowrap; }}
/* 섹션 오버라인(모노) + 헤어라인 */
.nm-sec {{ display:flex; align-items:center; gap:10px; margin:18px 0 2px; }}
.nm-sec .ov {{ font-family:{_MONO}; font-size:11px; letter-spacing:.14em; color:{_ACCENT_TEXT};
  white-space:nowrap; }}
.nm-sec .rule {{ flex:1; height:1px; background:{_LINE}; }}
.nm-sec .opt {{ font-size:12px; color:{_FAINT}; white-space:nowrap; }}
/* 우측 체크리스트 aside — 헤어라인(좌측 보더), 카드 아님 */
.nm-check {{ display:flex; flex-direction:column; gap:10px; padding-left:20px;
  border-left:1px solid {_LINE_SEC}; }}
.nm-check .hd {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
.nm-check .hd .ov {{ font-family:{_MONO}; font-size:10px; letter-spacing:.14em; color:{_FAINT}; }}
.nm-check .hd .cnt {{ font-family:{_MONO}; font-size:11.5px; font-weight:600; color:{_ACCENT_TEXT}; }}
.nm-check .bar {{ height:3px; border-radius:999px; background:{_LINE}; overflow:hidden; }}
.nm-check .bar > i {{ display:block; height:100%; background:{_ACCENT}; }}
.nm-check .items {{ display:flex; flex-wrap:wrap; gap:9px 16px; margin-top:2px; }}
.nm-check .ci {{ flex:1 1 130px; min-width:0; display:flex; align-items:center; gap:9px;
  font-size:13px; color:{_INK2}; }}
.nm-check .ci .box {{ width:14px; height:14px; border-radius:4px; border:1px solid {_LINE_HDR};
  flex:0 0 14px; display:inline-flex; align-items:center; justify-content:center; }}
.nm-check .ci.on .box {{ background:{_ACCENT}; border-color:{_ACCENT}; color:#fff; font-size:10px; }}
.nm-check .ci.on {{ color:{_INK}; }}
.nm-check .note {{ margin:8px 0 0; padding-top:12px; border-top:1px solid {_LINE};
  font-size:12px; line-height:1.6; color:{_WEAK}; text-wrap:pretty; }}
/* 하단 제출 바 — 헤어라인 위, 우측 정렬 */
.nm-submitbar {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between;
  gap:12px 16px; padding:16px 0 0; margin-top:22px; border-top:1px solid {_LINE_SEC}; }}
.nm-submitbar .hint {{ font-size:12.5px; color:{_WEAK}; }}
.nm-submitbar .hint b {{ color:{_INK}; font-weight:600; }}
/* 03 · 사진 첨부(선택) — 업로더 드롭존을 §2 팔레트 헤어라인·점선으로 정돈(카드 아님). */
.st-key-nm_photo_zone [data-testid="stFileUploaderDropzone"] {{
  background:#fbfaf8 !important; border:1px dashed #dcd6cc !important; border-radius:10px !important; }}
.st-key-nm_photo_zone [data-testid="stFileUploaderDropzone"]:hover {{ border-color:{_LINE_HDR} !important; }}
/* 스테이징 썸네일 — 헤어라인 프레임(카드 그림자 없음). */
.st-key-nm_photo_thumbs [data-testid="stImage"] img {{
  border:1px solid {_LINE} !important; border-radius:8px !important; }}
/* 삭제 버튼(썸네일 아래) — 히트영역 32px, 중립 텍스트. */
[class*="st-key-nm_photo_del_"] button {{ min-height:32px !important; border-radius:8px !important;
  font-size:12.5px !important; color:{_INK2} !important; }}
/* ≤900px: 체크리스트가 본문 아래로 내려간다(좁은 폭·모바일). */
@media (max-width:900px) {{
  .st-key-nm_form_wrap div[data-testid="stHorizontalBlock"] {{ flex-direction:column; }}
  .st-key-nm_form_wrap div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    width:100% !important; flex:1 1 100% !important; }}
  .nm-check {{ padding-left:0; border-left:0; border-top:1px solid {_LINE_SEC}; padding-top:14px; }}
}}
</style>
"""


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _dept_display(dept_code: str) -> str:
    code = _clean(dept_code)
    if not code:
        return "미지정"
    try:
        depts = db.get_departments()
        hit = depts[depts["dept_code"].astype(str).str.strip() == code]
        if not hit.empty:
            name = _clean(hit.iloc[0].get("dept_name"))
            if name:
                return f"{name} ({code})"
    except Exception:  # noqa: BLE001 — 표시 폴백.
        pass
    return code


def _reset_form_state() -> None:
    for key in _FORM_WIDGET_KEYS:
        st.session_state.pop(key, None)
    _reset_photo_stage()


def _reset_photo_stage() -> None:
    """스테이징한 사진 bytes·처리 표식을 세션에서 정리한다(제출 성공·화면 이탈 시 메모리 잔류 방지)."""
    st.session_state.pop(_STAGE_KEY, None)
    st.session_state.pop(_STAGE_SEEN_KEY, None)


def _ingest_photo(upload, name: str) -> str | None:
    """업로드 1장을 선택 즉시 크기 사전검사→검증·압축해 스테이지에 추가한다. 오류 문구(없으면 None).

    ``upload`` 은 ``.size``/``.getvalue()`` 를 가진 UploadedFile. **getvalue() 로 전량 적재하기
    전에** ``.size`` 로 원본 상한(10MB/장)과 스테이징 누적 상한을 먼저 차단한다(대용량 메모리
    적재 방지). 그다음 photo_storage 순수 계약(확장자+매직바이트 jpg/png/webp·JPEG 정규화)으로
    검증·압축해 잘못된 파일을 제출 전에 즉시 거른다(modules 무수정 — API 소비만)."""
    stage = st.session_state.setdefault(_STAGE_KEY, [])
    if len(stage) >= photo_storage.MAX_PHOTOS:
        return f"사진은 최대 {photo_storage.MAX_PHOTOS}장까지 첨부할 수 있습니다. '{name}'은(는) 제외했습니다."
    # 원본 크기 사전 검사(getvalue 전 — 대용량은 메모리에 올리지 않고 차단).
    size = getattr(upload, "size", None)
    if isinstance(size, int) and size > _MAX_UPLOAD_BYTES:
        return f"{name}: 이미지 용량이 너무 큽니다. 최대 {_MAX_UPLOAD_MB}MB 까지 첨부할 수 있습니다."
    staged_total = sum(int(p.get("size") or 0) for p in stage)
    if isinstance(size, int) and staged_total + size > _STAGE_TOTAL_CAP_BYTES:
        return (f"{name}: 첨부 사진 총 용량이 한도({_STAGE_TOTAL_CAP_MB}MB)를 초과했습니다. "
                "큰 사진을 줄이거나 일부만 첨부하세요.")
    try:
        data = upload.getvalue()
    except Exception:  # noqa: BLE001 — 업로더 스트림 읽기 실패(원문 비노출).
        return f"{name}: 파일을 읽을 수 없습니다."
    try:
        out, _ext, _ctype = photo_storage.validate_and_compress(data, name)
    except photo_storage.PhotoValidationError as exc:
        return f"{name}: {exc}"
    except Exception:  # noqa: BLE001 — 손상/미지원 이미지(원문 비노출).
        return f"{name}: 이미지를 처리할 수 없습니다."
    stage.append({"id": uuid.uuid4().hex, "name": name, "bytes": out,
                  "size": int(size) if isinstance(size, int) else len(data)})
    return None


def _render_photo_stage() -> None:
    """03 · 사진 첨부(선택) — 업로더(다중)+카메라(expander) 스테이징 + 썸네일·개별 삭제.

    st.form 밖에서 렌더한다(반응형 상호작용). 선택 즉시 검증·압축해 세션에 스테이징하고,
    실제 저장은 제출 성공 후 _attach_staged_photos 가 db API 로 수행한다."""
    _section("03", "사진 첨부", opt="선택")
    stage = st.session_state.setdefault(_STAGE_KEY, [])
    seen = st.session_state.setdefault(_STAGE_SEEN_KEY, set())
    errors: list[str] = []

    with st.container(key="nm_photo_zone"):
        ups = st.file_uploader(
            "현장 사진 선택", type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True, key=_UP_KEY, label_visibility="collapsed",
            max_upload_size=_MAX_UPLOAD_MB,  # 위젯 단위 상한(MB) — 서버 config 와 병행 차단.
            help=f"JPG·PNG·WEBP · 최대 {photo_storage.MAX_PHOTOS}장 · 원본 {_MAX_UPLOAD_MB}MB 이하",
        )
    for f in (ups or []):
        fid = getattr(f, "file_id", None) or f.name
        if fid in seen:
            continue
        seen.add(fid)
        err = _ingest_photo(f, f.name or "사진.jpg")
        if err:
            errors.append(err)

    with st.expander("사진 촬영 (카메라)", expanded=False):
        cam = st.camera_input("사진 촬영", key=_CAM_KEY, label_visibility="collapsed")
    if cam is not None:
        fid = getattr(cam, "file_id", None)
        if fid and fid not in seen:
            seen.add(fid)
            err = _ingest_photo(cam, "촬영사진.jpg")
            if err:
                errors.append(err)

    for e in errors:
        banner("warn", e)

    if stage:
        with st.container(key="nm_photo_thumbs"):
            cols = st.columns(photo_storage.MAX_PHOTOS)
            for i, ph in enumerate(stage):
                with cols[i]:
                    st.image(ph["bytes"], width="stretch")
                    if st.button("삭제", key=f"nm_photo_del_{ph['id']}", width="stretch"):
                        st.session_state[_STAGE_KEY] = [p for p in stage if p["id"] != ph["id"]]
                        st.rerun()

    st.markdown(
        f"<div style='font-size:12px;color:{_WEAK};margin-top:8px;line-height:1.6;'>"
        f"{len(stage)} / {photo_storage.MAX_PHOTOS}장 · 사진은 선택 항목입니다. "
        f"선택한 사진은 <b style='color:{_INK};font-weight:600;'>[제안서 제출]</b> 시 함께 첨부됩니다.</div>",
        unsafe_allow_html=True,
    )


def _identity_row(user: dict) -> None:
    """신고자·소속을 읽기 전용으로 표시(서버가 세션에서 확정) — 카드 아님(헤어라인)."""
    name = _clean(user.get("name")) or "(이름 미확인)"
    emp_no = _clean(user.get("emp_no"))
    dept = _dept_display(user.get("dept_code"))
    st.markdown(
        "<div class='nm-reporter'><span class='ov'>REPORTER</span>"
        f"<span class='it'><span class='k'>신고자</span><span class='v'>{escape(name)}</span></span>"
        f"<span class='it'><span class='k'>사번</span><span class='v'>{escape(emp_no)}</span></span>"
        f"<span class='it'><span class='k'>소속</span><span class='v'>{escape(dept)}</span></span>"
        "<span class='lock'>로그인 정보로 자동 지정 · 수정 불가</span></div>",
        unsafe_allow_html=True,
    )


def _section(num: str, label: str, opt: str = "") -> None:
    right = f"<span class='opt'>{escape(opt)}</span>" if opt else ""
    st.markdown(
        f"<div class='nm-sec'><span class='ov'>{escape(num)} · {escape(label)}</span>"
        f"<span class='rule'></span>{right}</div>",
        unsafe_allow_html=True,
    )


def _field_filled(key: str, val) -> bool:
    if key == "nm_f_incident_date":
        return val is not None
    return bool(str(val or "").strip())


def _checklist_html() -> str:
    """필수항목 체크리스트 + 진행 바 — st.form 제약상 렌더 시점 세션 값 기준(직전 rerun)."""
    items, done = [], 0
    for label, key in _REQUIRED:
        on = _field_filled(key, st.session_state.get(key))
        done += 1 if on else 0
        mark = "✓" if on else ""
        cls = "ci on" if on else "ci"
        items.append(f"<div class='{cls}'><span class='box'>{mark}</span><span>{escape(label)}</span></div>")
    total = len(_REQUIRED)
    pct = round(done / total * 100) if total else 0
    return (
        "<div class='nm-check'><div class='hd'><span class='ov'>CHECKLIST</span>"
        f"<span class='cnt'>{done} / {total}</span></div>"
        f"<div class='bar'><i style='width:{pct}%'></i></div>"
        f"<div class='items'>{''.join(items)}</div>"
        "<p class='note'>필수 항목을 모두 채우면 제출할 수 있습니다. 진행 표시는 마지막 반영 "
        "시점 기준이며, 제출 시 전체가 검증됩니다.</p></div>"
    )


def _readiness_gate() -> bool:
    probe = db.near_miss_schema_probe()
    if probe == "READY":
        return True
    if probe == "NOT_READY":
        banner("warn", "아차사고 스키마가 아직 준비되지 않아 신청을 저장할 수 없습니다. "
                       "스키마 적용 후 다시 시도하세요.")
    else:  # PROBE_ERROR
        banner("danger", "아차사고 스키마 상태를 확인하지 못했습니다. 잠시 후 다시 시도하세요.")
    return False


def render(user: dict) -> None:
    _SUBMIT_DESC = "현장에서 발견한 아차사고(near-miss)를 접수 등록합니다. 접수 후 상태는 제출됨(SUBMITTED)입니다."
    # 제목 크롬만(아이콘 툴바 밴드 없음 §0-3) — 아이콘은 상단 52px 헤더에만.
    erp.screen_frame(
        SCREEN_ARCHETYPE,
        title="아차사고 등록",
        desc=_SUBMIT_DESC,
        breadcrumb="아차사고 › 아차사고 등록",
        badges=scaffold.mode_badge(),
    )
    st.markdown(_FORM_CSS, unsafe_allow_html=True)

    done = st.session_state.get(_DONE_KEY)
    if done:
        _render_post_submit(done)
        return

    can_submit = _readiness_gate()

    # §1-D 폼형: 좌측 폼(01/02 섹션) + 우측 필수 체크리스트(≤900px 아래로 wrap).
    with st.container(key="nm_form_wrap"):
        form_col, check_col = st.columns([2.7, 1.0], vertical_alignment="top")
        with form_col:
            with st.form("near_miss_submit_form", clear_on_submit=False):
                _identity_row(user)

                # ── 01 · 기본 정보 ──
                _section("01", "기본 정보")
                c1, c2 = st.columns([2, 1])  # 작업명 2 1 240 / 발생일 1 1 150
                with c1:
                    work_name = st.text_input("작업명 *", max_chars=120, key="nm_f_work_name",
                                              placeholder="예: 3라인 컨베이어 벨트 점검")
                with c2:
                    incident_date = st.date_input("발생일 *", value=date.today(),
                                                  format="YYYY-MM-DD", key="nm_f_incident_date")
                cause_opts = [""] + list(db.NEAR_MISS_CAUSE_CODES)
                cc1, cc2 = st.columns([1, 2])  # 발생원인(코드) / 발생원인 상세
                with cc1:
                    cause_code = st.selectbox(
                        "발생원인 *", cause_opts, index=0, key="nm_f_cause_code", width=200,
                        format_func=lambda c: "— 선택 —" if c == "" else f"{_CAUSE_LABELS.get(c, c)} ({c})",
                    )
                with cc2:
                    cause_detail = st.text_input("발생원인 상세 *", max_chars=200,
                                                 key="nm_f_cause_detail",
                                                 placeholder="원인을 구체적으로")

                # ── 02 · 상황 기술 ──
                _section("02", "상황 기술")
                incident_content = st.text_area(
                    "사고내용 *", height=120, key="nm_f_incident_content",
                    placeholder="무슨 일이 있었는지(아차사고 상황)를 구체적으로 적어 주세요",
                )
                wc1, wc2 = st.columns(2)  # 작업내용 / 작업현장 상황설명
                with wc1:
                    work_content = st.text_area("작업내용 *", height=90, key="nm_f_work_content",
                                                placeholder="어떤 작업을 하고 있었는지")
                with wc2:
                    site_description = st.text_area("작업현장 상황설명 *", height=90,
                                                    key="nm_f_site_description",
                                                    placeholder="현장 상황 · 주변 환경")
                countermeasure = st.text_area("예방대책 *", height=90, key="nm_f_countermeasure",
                                              placeholder="재발을 막기 위한 제안 대책")

                # ── 하단 제출 바(임시 저장 없음 — 현재 앱 미지원, 거짓 어포던스 금지) ──
                st.markdown(
                    "<div class='nm-submitbar'><span class='hint'>제출 후 상태는 "
                    "<b>제출됨(SUBMITTED)</b>이 됩니다. 사진(선택)은 아래 03에서 첨부합니다.</span></div>",
                    unsafe_allow_html=True,
                )
                submitted = erp.form_submit("제안서 제출", disabled=not can_submit)

            # 03 · 사진 첨부 — st.form 밖(반응형 상호작용). 제출 성공 후 db API 로 첨부한다.
            _render_photo_stage()
        with check_col:
            st.markdown(_checklist_html(), unsafe_allow_html=True)

    if not submitted:
        return

    missing = _validate({
        "work_name": work_name,
        "cause_code": cause_code,
        "cause_detail": cause_detail,
        "incident_content": incident_content,
        "incident_date": incident_date,
        "work_content": work_content,
        "countermeasure": countermeasure,
        "site_description": site_description,
    })
    if missing:
        banner("danger", "필수 항목을 입력하세요: " + ", ".join(missing))
        return

    # 제안 등급은 등록에서 제외(평가 단계 소관). 사진은 생성 payload 에 싣지 않고 빈 배열로
    # 시작한다 — 업로드 API 가 '이미 존재하는 SUBMITTED 보고서'를 요구하므로, 스테이징한 사진은
    # 보고서 생성 성공 후 _attach_staged_photos 가 db.upload_near_miss_photo 로 append 한다
    # (스테이징-후-첨부). 즉 photo_paths=[] 는 미구현(GATED)이 아니라 '생성 시점엔 아직 비어 있음'.
    payload = {
        "work_name": _clean(work_name),
        "cause_code": cause_code,
        "cause_detail": _clean(cause_detail),
        "incident_date": incident_date.isoformat(),
        "work_content": _clean(work_content),
        "incident_content": _clean(incident_content),
        "countermeasure": _clean(countermeasure),
        "site_description": _clean(site_description),
        "photo_paths": [],  # 생성 시점엔 빈 배열 — 제출 성공 후 사진을 db API 로 첨부(append).
    }
    _persist_and_report(payload)


def _validate(fields: dict) -> list[str]:
    """필수 항목 검증. 비어 있는 항목의 한글 라벨 목록을 반환한다(계약 불변)."""
    labels = {
        "work_name": "작업명",
        "cause_code": "발생원인",
        "cause_detail": "발생원인 상세",
        "incident_content": "사고내용",
        "incident_date": "발생일",
        "work_content": "작업내용",
        "countermeasure": "예방대책",
        "site_description": "작업현장 상황설명",
    }
    missing: list[str] = []
    for key, label in labels.items():
        value = fields.get(key)
        if value in (None, "") or (isinstance(value, str) and not value.strip()):
            missing.append(label)
    return missing


def _persist_and_report(payload: dict) -> None:
    """저장을 시도하고 lifecycle PersistResult/ledger_banner 패턴으로 결과를 표시한다.

    도메인 검증 오류(ValueError)는 그대로 노출하고, 그 외 예외는 원문을 감춰 '결과 불명'으로 접는다."""
    try:
        record = db.create_near_miss_report(payload, current_user=auth.get_current_user())
    except ValueError as exc:
        ledger_banner(PersistResult.failure(_PAGE_ID, [payload.get("work_name") or "신청"],
                                            str(exc), retryable=True))
        return
    except Exception:  # noqa: BLE001 — raw 예외 문구 비노출.
        ledger_banner(PersistResult.unresolved(
            _PAGE_ID, "저장 결과를 확인할 수 없습니다. 목록을 재조회한 뒤 다시 시도하세요."))
        return

    report_no = _clean((record or {}).get("report_no")) or "(채번 확인 필요)"
    # 보고서 생성 성공 → 스테이징한 사진을 db API 로 첨부(스테이징-후-첨부). 개별 실패는 경고로
    # 표면화하되 제출 자체는 성공 처리한다(사진은 선택 항목). 처리 후 세션 스테이지를 정리한다.
    photo_warnings = _attach_staged_photos((record or {}).get("id"))
    _reset_photo_stage()
    st.session_state[_DONE_KEY] = {"report_no": report_no, "photo_warnings": photo_warnings}
    st.rerun()


def _attach_staged_photos(report_id) -> list[str]:
    """제출 성공 후 스테이징 사진을 순차 첨부한다(소유자+SUBMITTED 게이트는 파사드가 재확인).

    신원은 위젯이 아니라 세션 사용자에서 서버측 확정한다(위조 방지). 개별 실패 문구 목록을
    반환한다(빈 목록이면 전부 성공)."""
    stage = st.session_state.get(_STAGE_KEY) or []
    if not report_id or not stage:
        return []
    current_user = auth.get_current_user()
    warnings: list[str] = []
    for ph in stage:
        try:
            db.upload_near_miss_photo(report_id, ph["bytes"], ph["name"], current_user=current_user)
        except ValueError as exc:
            warnings.append(f"{ph['name']}: {exc}")
        except Exception:  # noqa: BLE001 — 저장 백엔드 오류(원문 비노출).
            warnings.append(f"{ph['name']}: 첨부하지 못했습니다.")
    return warnings


def _render_post_submit(done: dict) -> None:
    """제출 완료 결과 배너 + 다음 작업 선택([내 아차사고에서 확인]·[새 아차사고 등록])."""
    report_no = _clean(done.get("report_no")) or "(채번 확인 필요)"
    ledger_banner(PersistResult.success(_PAGE_ID, [report_no]))
    banner("success",
           f"아차사고를 접수했습니다. 접수번호 {report_no} · 상태 제출됨(SUBMITTED)")

    # 사진 첨부 부분 실패 안내 — 보고서는 저장됐고 SUBMITTED 동안 '내 아차사고'에서 재첨부 가능.
    warns = done.get("photo_warnings") or []
    if warns:
        banner("warn",
               "일부 사진을 첨부하지 못했습니다: " + " / ".join(warns)
               + " — 제출됨(SUBMITTED) 상태 동안 '내 아차사고'에서 다시 첨부할 수 있습니다.")

    st.markdown(
        f"<div style='font-size:12.5px;color:{_INK2};margin:6px 0 4px;'>다음 작업을 선택하세요.</div>",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("내 아차사고에서 확인", type="primary", width="stretch",
                     key="nm_done_go_my", icon=":material/inbox:"):
            _reset_form_state()
            st.session_state.pop(_DONE_KEY, None)
            ui.request_nav({"type": "page", "target": "near_miss_my"})
    with c2:
        if st.button("새 아차사고 등록", width="stretch",
                     key="nm_done_new", icon=":material/add:"):
            _reset_form_state()
            st.session_state.pop(_DONE_KEY, None)
            st.rerun()
