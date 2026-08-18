# Third-Party Notices

이 저장소의 `.claude/skills/ux-review/`, `.claude/skills/visual-review/`,
`.claude/skills/screen-design/`(Stage 0 절)는 아래 MIT 라이선스 프로젝트의 구조·루브릭을
차용(보존 이식)해 workops 맥락으로 재작성한 것입니다. 각 원저작물의 저작권 고지와
MIT 허가 문구를 아래에 보존합니다.

MIT License 허가 문구(각 저작물 공통):

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## 차용 출처

1. **wondelai/skills — ux-heuristics** (https://github.com/wondelai/skills)
   MIT License, Copyright (c) 2025 Wondel.ai sp. z o.o.
   → `ux-review`: Krug 원리·심각도 Level 0–4·진단 질문 구조.

2. **mastepanoski/claude-skills — nielsen-heuristics-audit**
   (https://github.com/mastepanoski/claude-skills)
   MIT License, Copyright (c) 2026 mastepanoski
   → `ux-review`: 심각도 등급표(4=작업차단·데이터손실·보안)·Must/Should/Nice 산출 형식.

3. **jezweb/claude-skills — design-review** (https://github.com/jezweb/claude-skills)
   MIT License, Copyright (c) 2025 Jeremy Dawes (Jezweb)
   → `visual-review`: 7축 루브릭·High/Medium/Low 버킷·squint test·판정 기준.

4. **Dammyjay93/interface-design** (https://github.com/Dammyjay93/interface-design)
   MIT License, Copyright (c) 2026 Damola Akinleye
   → `screen-design` Stage 0: intent 3문·뷰당 초점 1개·밀도 사전 명시·use-what-exists·
   컴포넌트 체크포인트·상태 완비 절차.

## 동봉 폰트

5. **Noto Sans CJK KR** (`fonts/NotoSansKR-Regular.ttf`, Google Noto 프로젝트)
   SIL Open Font License 1.1 (OFL) — 배포 경량화를 위해 한글(AC00-D7A3)+라틴+구두점으로 서브셋. Copyright © 2014-2021 Adobe (https://github.com/adobe-fonts),
   Google LLC. → 아차사고 보고서 A4 PDF(`views/near_miss_pdf.py`)의 한글 렌더에 동봉·재배포.

   > This Font Software is licensed under the SIL Open Font License, Version 1.1.
   > This license is available with a FAQ at: https://scripts.sil.org/OFL

   **라이선스 전문**: SIL Open Font License 1.1 의 전체 조문을 [`fonts/OFL.txt`](fonts/OFL.txt)
   에 원문 그대로 동봉한다(OFL §의 "재배포 시 라이선스 사본 포함" 요건 충족). 요약이 아니라
   원문이 정본이며, 폰트를 재배포할 때 이 파일을 함께 배포한다.

   비고: 배포 이식성을 위해 OFL 한글 폰트를 동봉했다. `views/near_miss_pdf.py` 는 동봉
   폰트를 우선하고, 없으면 시스템 한글 폰트(맑은고딕/Noto/Nanum)로 폴백한다.

6. **IBM Plex Sans KR · IBM Plex Mono** (UI 서체, `DESIGN.md` §1.2 정본)
   SIL Open Font License 1.1 (OFL), Copyright © 2017 IBM Corp.
   → `modules/ui.py:37` 이 **Google Fonts CDN 에서 로드**한다(`@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans+KR')`).

   **이 저장소는 IBM Plex 를 동봉·재배포하지 않는다.** `fonts/` 에는 PDF 용 Noto Sans CJK KR
   만 있다. OFL 의 재배포 고지 요건은 재배포가 없으므로 발생하지 않으며, 이 항목은 사용
   사실을 밝히기 위한 기록이다.

   > 주의: CDN 로드이므로 **외부망이 차단된 환경에서는 폰트를 못 받고 폴백**(맑은고딕 등)
   > 으로 떨어진다. `DESIGN.md` §1.2 가 정한 서체가 환경에 따라 지켜지지 않는다는 뜻이다
   > (미해결 — `DESIGN.md` §7.2-23).
