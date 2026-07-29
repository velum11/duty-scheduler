# Third-Party Notices

이 저장소의 `.claude/skills/duty-ux/`, `.claude/skills/duty-visual-critique/`,
`.claude/skills/duty-erp-ui/`(Stage 0 절)는 아래 MIT 라이선스 프로젝트의 구조·루브릭을
차용(보존 이식)해 duty-scheduler 맥락으로 재작성한 것입니다. 각 원저작물의 저작권 고지와
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
   → `duty-ux`: Krug 원리·심각도 Level 0–4·진단 질문 구조.

2. **mastepanoski/claude-skills — nielsen-heuristics-audit**
   (https://github.com/mastepanoski/claude-skills)
   MIT License, Copyright (c) 2026 mastepanoski
   → `duty-ux`: 심각도 등급표(4=작업차단·데이터손실·보안)·Must/Should/Nice 산출 형식.

3. **jezweb/claude-skills — design-review** (https://github.com/jezweb/claude-skills)
   MIT License, Copyright (c) 2025 Jeremy Dawes (Jezweb)
   → `duty-visual-critique`: 7축 루브릭·High/Medium/Low 버킷·squint test·판정 기준.

4. **Dammyjay93/interface-design** (https://github.com/Dammyjay93/interface-design)
   MIT License, Copyright (c) 2026 Damola Akinleye
   → `duty-erp-ui` Stage 0: intent 3문·뷰당 초점 1개·밀도 사전 명시·use-what-exists·
   컴포넌트 체크포인트·상태 완비 절차.
