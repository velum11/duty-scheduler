# 생산 근무표 관리

회사 생산 현장 근무표를 등록, 수정, 조회하기 위한 웹 시스템입니다.

사용자 화면에 표시되는 앱 이름은 항상 **생산 근무표 관리**로 통일합니다.  
이 프로젝트는 Streamlit 기반으로 개발하며, 최종 저장소는 Supabase PostgreSQL을 목표로 합니다.

화면 디자인과 개발 기준은 아래 문서를 따릅니다.

```text
CLAUDE.md
DESIGN.md
docs/
```

---

## 개발 방향

이 시스템은 자동 근무표 생성기가 아닙니다.  
근무는 사람이 직접 입력하고, 시스템은 다음 기능을 제공합니다.

- 사번 로그인
- 권한별 메뉴 분기
- 기준정보 관리
- 근무표 등록/수정
- 전체 근무표 조회
- 직원별 내 근무표 조회
- 엑셀 복사/붙여넣기 기반 스프레드시트 입력
- Supabase 저장
- 명시적 데이터 모드 선택(`sample` 또는 `supabase`)

관리자와 매니저 화면은 `DESIGN.md` 기준의 SAP/ERP 스타일 App Shell을 사용합니다.

```text
좌측 1차 아이콘 메뉴
좌측 2차 업무 메뉴 패널
우측 메인 콘텐츠 영역
```

직원 화면은 모바일 웹 조회 화면을 기준으로 합니다.

---

## 현재 구현 범위

현재 저장소는 다음 기능을 우선 포함합니다.

- 실행 가능한 Streamlit 앱 구조
- 사번 입력 로그인
- 쿠키 기반 로그인 유지
- 로그아웃
- USER / MANAGER / ADMIN 권한 구분
- 로컬 샘플 데이터 실행
- 내 근무표 기본 조회
- App Shell 적용 준비 구조

로컬 실행은 `DUTY_DATA_MODE=sample` 또는 `[app].data_mode="sample"`을 명시해야 합니다.

---

## 실행 방법

### 1. 가상환경 생성

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 2. 의존성 설치

```powershell
pip install -r requirements.txt
```

### 3. 앱 실행

```powershell
$env:DUTY_DATA_MODE = "sample"
python -m streamlit run app.py
```

브라우저에서 아래 주소로 접속합니다.

```text
http://localhost:8501
```

---

## 테스트용 샘플 사번

| 사번 | 이름 | 소속 | 권한 | 확인 용도 |
|---|---|---|---|---|
| 1001 | 김관리 | PET생산부(본동) A조 | ADMIN | 전체 메뉴 확인 |
| 1002 | 이책임 | PET생산부(본동) A조 | MANAGER | 근무표 관리 메뉴 확인 |
| 1003 | 박근무 | PET생산부(본동) A조 | USER | 내 근무표 조회 확인 |
| 2001 | 퇴사자 | PET생산부(본동) B조 | 비활성 | 로그인 거부 확인 |

---

## 기본 확인 항목

앱 실행 후 다음 항목을 확인합니다.

- Supabase 설정 없이 앱 실행 가능
- 로컬 샘플 데이터 로딩 가능
- 1001 로그인 시 ADMIN 메뉴 표시
- 1002 로그인 시 MANAGER 메뉴 표시
- 1003 로그인 시 USER용 내 근무표 화면 표시
- 2001 로그인 거부
- 새로고침 후 로그인 유지
- 로그아웃 동작
- 병원/간호 관련 용어 없음
- 사용자 화면에 개발 단계 문구 없음

사용자 화면에는 아래 표현을 표시하지 않습니다.

```text
Phase
MVP
Demo
데모
준비 중
구현 예정
오픈 후 이용 가능
샘플 앱
테스트 화면
AI
```

---

## 폴더 구조

```text
duty-scheduler/
├── app.py
├── modules/
│   ├── auth.py
│   ├── config.py
│   ├── db.py
│   ├── nav.py
│   ├── sample_data.py
│   └── ui.py
├── views/
│   ├── login.py
│   ├── dashboard.py
│   ├── workspace.py
│   └── my_schedule.py
├── data/
│   └── sample/
├── docs/
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── CLAUDE.md
├── DESIGN.md
├── README.md
└── requirements.txt
```

추후 기능이 추가되면 `views/`와 `modules/`는 다음 구조로 확장합니다.

```text
views/
├── dashboard.py
├── master_users.py
├── master_departments.py
├── master_teams.py
├── master_work_types.py
├── schedule_edit.py
├── schedule_view.py
└── my_schedule.py

modules/
├── auth.py
├── config.py
├── db.py
├── nav.py
├── ui.py
├── schedule.py
└── validators.py
```

---

## 주요 문서

| 문서 | 내용 |
|---|---|
| `CLAUDE.md` | Claude Code 작업 기준 |
| `DESIGN.md` | SAP/ERP 스타일 화면 디자인 기준 |
| `docs/requirements.md` | 요구사항 |
| `docs/screens.md` | 화면 설계 |
| `docs/database.md` | Supabase 테이블 설계 |
| `docs/development-plan.md` | 개발 계획 |

---

## Supabase 설정

Supabase 연결 정보는 코드에 직접 작성하지 않습니다.

설정 파일은 다음 위치를 사용합니다.

```text
.streamlit/secrets.toml
```

예시는 다음 파일을 참고합니다.

```text
.streamlit/secrets.toml.example
```

데이터 모드와 Supabase 접속정보는 다음처럼 설정합니다.

```toml
[app]
data_mode = "supabase"

[supabase]
url = "https://...supabase.co"
service_role_key = "..."
test_project = false
```

환경변수 `DUTY_DATA_MODE`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`도 사용할 수
있습니다. Supabase 모드의 연결 실패는 sample 모드로 자동 전환되지 않습니다.
`service_role_key`는 서버 측 secrets에만 두며 브라우저로 전달하지 않습니다.

---

## 보안 한계

현재 로그인 방식은 사번만 입력하는 간단 로그인입니다.

따라서 타인의 사번을 아는 사람이 해당 사용자로 로그인할 수 있습니다.  
초기 사내 사용 범위에서는 이 한계를 인지하고 사용하며, 추후 다음 방식으로 보완할 수 있습니다.

- 사번 + 이름 확인
- 사번 + PIN
- 관리자 승인
- 정식 인증 방식 도입
