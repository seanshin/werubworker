# WeruBWorker GUI 한국어(i18n) 지원 기획서

## 1. 개요

WeruBWorker GUI의 전체 UI를 한국어로 지원하기 위한 국제화(i18n) 작업 기획서.
현재 모든 텍스트가 영어로 하드코딩되어 있으며, i18n 인프라가 전혀 없는 상태.

### 목표
- 전체 UI를 한국어/영어 전환 가능하도록 변경
- 향후 다른 언어 추가가 용이한 구조 확립
- 기존 기능에 영향 없이 적용

### 범위
- 프론트엔드(GUI): `surfaces/gui/src/` 내 모든 사용자 대면 문자열
- 백엔드(서버): 도구명, 에러 메시지 등 UI에 노출되는 서버 문자열

---

## 2. 현황 분석

| 항목 | 현황 |
|------|------|
| i18n 라이브러리 | 없음 |
| 하드코딩된 문자열 수 | **235개** (주요 11개 파일 기준) |
| 전체 추정 (76개 파일) | **~600개** |
| 대상 소스 파일 수 | 76개 (.tsx/.ts) |
| 기존 번역 키 | 없음 |

### 문자열 분포 (실측 기반)

| 카테고리 | 수량 | 예시 |
|----------|------|------|
| 버튼/메뉴 라벨 | ~80 | Save, Cancel, New session, Retry |
| 도움말/설명문 | ~60 | 설정 안내, 온보딩 설명, 권한 설명 |
| 도구 액션 설명 | ~35 | "Wrote", "Edited", "Ran a command" |
| 상태/피드백 메시지 | ~35 | Loading, Connected, Error |
| 빈 상태 메시지 | ~25 | "No conversations yet", "No previewable files" |

---

## 3. 대상 컴포넌트 (실측 기준)

### 3.1 핵심 UI (P0) — 107개 문자열

| 파일 | 문자열 수 | 주요 내용 |
|------|-----------|-----------|
| App.tsx | 21 | 제안 문구, 세션 상태, 타이틀 |
| Sidebar.tsx | 27 | 네비게이션, 필터, 메뉴, 빈 상태 |
| Composer.tsx | 31 | 권한 모드, 첨부, 모델 선택, 플레이스홀더 |
| Transcript.tsx | 16 | 상태 라벨, 승인/거부, 사고 과정 |
| ApprovalCard.tsx | 15 | 도구 설명, 승인 버튼, 스킬 추가 |
| humanize.ts | 24 | 도구 액션 설명 (특수 처리 필요) |

### 3.2 설정 및 부가 UI (P1) — 86개 문자열

| 파일 | 문자열 수 | 주요 내용 |
|------|-----------|-----------|
| SettingsView.tsx | 38 | 탭, 섹션, 필드 라벨, 도움말 |
| Onboarding.tsx | 27 | 단계별 안내, 연동 설명, 버튼 |
| RightRail.tsx | 15 | 패널 제목, 아티팩트, 빈 상태 |
| ScheduledView.tsx | ~17 | 자동화 뷰 라벨 |
| AccessSection.tsx | ~15 | 접근 제어 라벨 |
| FolderGate.tsx | ~9 | 폴더 선택 UI |
| connectors/registry.tsx | ~33 | 커넥터 이름/설명 |
| providers/ProviderSetup.tsx | ~12 | API 제공자 정보 |

### 3.3 기타 컴포넌트 (P2) — ~42개 문자열

| 파일 | 문자열 수 | 주요 내용 |
|------|-----------|-----------|
| SkillsTab.tsx | 21 | 스킬 관리 UI (생성, 편집, 삭제) |
| GalleryModal.tsx | ~14 | 갤러리 콘텐츠 |
| PersonaView.tsx | ~11 | 페르소나 설정 |
| ModelChecklist.tsx | ~10 | 모델 체크리스트 |
| SessionIntro.tsx | ~9 | 세션 시작 안내 |
| UpdateBanner.tsx | ~5 | 업데이트 알림 |
| Dropdown.tsx | 0 | 데이터 기반 (번역 불필요) |

### 3.4 커넥터 상세 (P2) — ~126개 문자열

| 파일 | 문자열 수 |
|------|-----------|
| SlackHowItWorks.tsx | ~42 |
| SlackDetail.tsx | ~24 |
| AddConnectionModal.tsx | ~20 |
| GithubDetail.tsx | ~15 |
| GmailDetail.tsx | ~10 |
| Calendar, HubSpot, Accounts | ~15 |

---

## 4. 특수 처리 필요 사항

### 4.1 humanize.ts — 템플릿 기반 번역

이 파일은 도구 액션을 사람이 읽을 수 있는 문장으로 변환합니다.
단순 키-값 치환이 아닌 **문맥 기반 문장 조합** 패턴입니다.

```typescript
// 현재: 영어 문법에 맞춰 조합
"Wrote " + path          → "파일 작성: " + path
"Edited " + path         → "파일 편집: " + path
"Ran " + cmd             → "명령 실행: " + cmd
"Sent a message to " + x → x + "에 메시지 전송"
```

**주의**: 한국어는 어순이 다르므로(SOV), pre/post 패턴을 지원하는 번역 구조 필요.

### 4.2 동적 문자열 (복수형/카운트)

```typescript
// 영어: "Show 3 more"
// 한국어: "3개 더 보기" (수량 위치가 다름)
t('sidebar.showMore', { count: 3 })
```

i18next의 `interpolation` + `pluralization` 기능으로 처리.

### 4.3 서버 발생 문자열

서버(Python)에서 생성되어 UI에 표시되는 문자열:
- 도구명 (`run_shell`, `write_file` 등) — humanize.ts에서 변환
- 에러 메시지 — engine.py에서 `friendly_model_error()`로 생성
- 모델 역할 라벨 — manager.py `_MODEL_ROLES`에서 생성 (이미 한국어)

→ 서버 문자열은 Phase 3 이후 검토.

---

## 5. 기술 설계

### 5.1 라이브러리: react-i18next

| 후보 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **react-i18next** | React 최대 생태계, 네임스페이스, 복수형 | 번들 ~15KB | **채택** |
| react-intl | ICU 포맷 | 러닝커브 높음 | 불채택 |
| 자체 구현 | 경량 | 복수형/포맷 미지원 | 불채택 |

### 5.2 디렉토리 구조

```
surfaces/gui/src/
├── i18n/
│   ├── index.ts              # i18next 초기화
│   ├── locales/
│   │   ├── en/
│   │   │   ├── common.json       # 공통 (버튼, 상태, 에러)
│   │   │   ├── session.json      # 세션/채팅/사이드바
│   │   │   ├── settings.json     # 설정 페이지
│   │   │   ├── connectors.json   # 커넥터/연동
│   │   │   ├── automation.json   # 자동화/스케줄
│   │   │   ├── humanize.json     # 도구 액션 설명
│   │   │   ├── onboarding.json   # 온보딩
│   │   │   └── skills.json       # 스킬 관리
│   │   └── ko/
│   │       └── (동일 구조)
```

### 5.3 번역 키 네이밍 규칙

```
{컴포넌트}.{요소}.{세부}

예시:
common.button.save           → "저장"
common.button.cancel         → "취소"
common.status.loading        → "로딩 중..."
sidebar.nav.search           → "검색"
sidebar.nav.automations      → "자동화"
sidebar.empty.noConversations → "대화가 없습니다"
composer.placeholder.default → "코워커에게 물어보세요..."
composer.permission.discuss  → "대화"
composer.permission.approval → "승인 요청"
composer.permission.full     → "전체 접근"
settings.tab.general         → "일반"
settings.tab.models          → "모델"
humanize.tool.wrote          → "파일 작성:"
humanize.tool.edited         → "파일 편집:"
humanize.tool.ran            → "명령 실행:"
skills.action.add            → "스킬 추가"
skills.action.install        → "스킬 설치"
onboarding.welcome.title     → "WeruBWorker에 오신 것을 환영합니다"
```

### 5.4 i18n 초기화 코드

```typescript
// src/i18n/index.ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import enCommon from './locales/en/common.json';
import enSession from './locales/en/session.json';
import enSettings from './locales/en/settings.json';
import enHumanize from './locales/en/humanize.json';
import enOnboarding from './locales/en/onboarding.json';
import enSkills from './locales/en/skills.json';
import enConnectors from './locales/en/connectors.json';
import enAutomation from './locales/en/automation.json';

import koCommon from './locales/ko/common.json';
import koSession from './locales/ko/session.json';
import koSettings from './locales/ko/settings.json';
import koHumanize from './locales/ko/humanize.json';
import koOnboarding from './locales/ko/onboarding.json';
import koSkills from './locales/ko/skills.json';
import koConnectors from './locales/ko/connectors.json';
import koAutomation from './locales/ko/automation.json';

i18n.use(initReactI18next).init({
  resources: {
    en: {
      common: enCommon,
      session: enSession,
      settings: enSettings,
      humanize: enHumanize,
      onboarding: enOnboarding,
      skills: enSkills,
      connectors: enConnectors,
      automation: enAutomation,
    },
    ko: {
      common: koCommon,
      session: koSession,
      settings: koSettings,
      humanize: koHumanize,
      onboarding: koOnboarding,
      skills: koSkills,
      connectors: koConnectors,
      automation: koAutomation,
    },
  },
  lng: localStorage.getItem('openworker-language') || 'ko',
  fallbackLng: 'en',
  ns: ['common', 'session', 'settings', 'humanize', 'onboarding', 'skills', 'connectors', 'automation'],
  defaultNS: 'common',
  interpolation: { escapeValue: false },
});

export default i18n;
```

### 5.5 컴포넌트 적용 패턴

**일반 라벨:**
```tsx
// 변경 전
<button>Save</button>

// 변경 후
const { t } = useTranslation();
<button>{t('common.button.save')}</button>
```

**복수형/카운트:**
```tsx
// 변경 전
`Show ${count} more`

// 변경 후
t('sidebar.showMore', { count })

// ko/session.json: "{{count}}개 더 보기"
// en/session.json: "Show {{count}} more"
```

**humanize.ts (문맥 조합):**
```tsx
// 변경 전
return { pre: "Wrote ", obj: path };

// 변경 후
return { pre: t('humanize.tool.wrote'), obj: path };

// ko: "파일 작성: "  → "파일 작성: src/index.ts"
// en: "Wrote "        → "Wrote src/index.ts"
```

### 5.6 언어 전환 UI

설정 페이지(SettingsView.tsx) General 탭에 추가:

```
[일반] 탭
  언어 / Language
    ┌─────────────┐
    │ 한국어    ✓  │
    │ English     │
    └─────────────┘
```

```typescript
const changeLanguage = (lng: string) => {
  i18n.changeLanguage(lng);
  localStorage.setItem('openworker-language', lng);
};
```

---

## 6. 작업 단계 (Phase)

### Phase 1: 인프라 구축
| # | 작업 | 산출물 |
|---|------|--------|
| 1 | `i18next`, `react-i18next` 설치 | package.json |
| 2 | `src/i18n/` 초기화 코드 생성 | index.ts |
| 3 | `main.tsx`에 i18n import 추가 | main.tsx |
| 4 | `en/common.json` 생성 (공통 버튼/상태) | ~40개 키 |
| 5 | `ko/common.json` 생성 (한국어 번역) | ~40개 키 |
| 6 | SettingsView에 언어 전환 UI 추가 | Dropdown |
| 7 | 빌드 및 동작 검증 | — |

### Phase 2: 핵심 UI 적용 (P0, 107개 문자열)
| # | 작업 | 문자열 수 |
|---|------|-----------|
| 8 | Sidebar.tsx 추출 및 적용 | 27 |
| 9 | Composer.tsx 추출 및 적용 | 31 |
| 10 | App.tsx 추출 및 적용 | 21 |
| 11 | Transcript.tsx 추출 및 적용 | 16 |
| 12 | ApprovalCard.tsx 추출 및 적용 | 15 |
| 13 | humanize.ts 추출 및 적용 (특수 처리) | 24 |

### Phase 3: 설정 및 부가 UI (P1, 86개 문자열)
| # | 작업 | 문자열 수 |
|---|------|-----------|
| 14 | SettingsView.tsx 적용 | 38 |
| 15 | Onboarding.tsx 적용 | 27 |
| 16 | RightRail.tsx 적용 | 15 |
| 17 | ScheduledView.tsx 적용 | ~17 |
| 18 | AccessSection.tsx + FolderGate.tsx 적용 | ~24 |
| 19 | connectors/registry.tsx 적용 | ~33 |
| 20 | providers/ProviderSetup.tsx 적용 | ~12 |

### Phase 4: 스킬, 커넥터, 기타 (P2, ~168개 문자열)
| # | 작업 | 문자열 수 |
|---|------|-----------|
| 21 | SkillsTab.tsx 적용 | 21 |
| 22 | 커넥터 상세 페이지 전체 적용 | ~126 |
| 23 | 갤러리, 모델, 페르소나, 세션소개, 업데이트 | ~49 |

### Phase 5: 검증 및 마무리
| # | 작업 |
|---|------|
| 24 | 전체 UI 한국어 표시 스크린샷 검증 |
| 25 | 레이아웃 깨짐 확인 (긴 텍스트, 고정 너비) |
| 26 | 누락 문자열 점검 (영어 노출 탐색) |
| 27 | E2E 테스트 업데이트 (data-testid 전환) |
| 28 | 서버 발생 문자열 검토 및 처리 |

---

## 7. 용어집 (Glossary)

### 원어 유지 (음차)

| 영어 | 한국어 | 사유 |
|------|--------|------|
| Session | 세션 | 업계 표준 |
| Model | 모델 | 업계 표준 |
| Token | 토큰 | 업계 표준 |
| Persona | 페르소나 | 제품 고유 개념 |
| Skill | 스킬 | 제품 고유 개념 |
| Connector | 커넥터 | 업계 표준 |
| Workspace | 워크스페이스 | 업계 표준 |
| Inbox | 인박스 | 익숙한 용어 |
| Schedule | 스케줄 | 익숙한 용어 |

### 번역

| 영어 | 한국어 | 사유 |
|------|--------|------|
| Settings | 설정 | 직관적 |
| Automation | 자동화 | 직관적 |
| Approval | 승인 | 직관적 |
| Search | 검색 | 직관적 |
| Transcript | 대화 기록 | 맥락에 맞게 |
| Integration | 연동 | 직관적 |
| Artifact | 산출물 | 의미 전달 |
| Progress | 진행 상황 | 의미 전달 |
| New session | 새 세션 | 혼합 (동사+음차) |
| Full access | 전체 접근 | 직관적 |
| Ask for approval | 승인 요청 | 직관적 |
| Discuss | 대화 | 직관적 |

---

## 8. 주의사항

### 레이아웃
- 한국어는 영어 대비 텍스트 길이가 달라짐 (대체로 짧아지나, 설명문은 길어질 수 있음)
- 사이드바, 탭, 버튼 등 고정 너비 요소의 `overflow`, `text-overflow: ellipsis` 점검
- Composer 권한 모드 라벨 길이 확인

### 번역 품질
- 용어집 기반 일관성 유지
- 경어체 통일 (해요체: "~합니다", "~하세요")
- 기술 용어 무리한 번역 지양 (Token → ~~증표~~)

### 테스트
- 기존 E2E 테스트 (`surfaces/gui/e2e/`)는 영어 텍스트로 요소를 탐색하는 경우 있음
- `data-testid` 속성 기반으로 전환 필요 (i18n 무관하게 테스트 가능)
- `skills-*.spec.ts`, `approval-card.spec.ts` 등 확인 필요

---

## 9. 필요 패키지

```bash
cd surfaces/gui
npm install i18next react-i18next
```

추가 옵션 (Phase 5 검토):
```bash
npm install i18next-browser-languagedetector  # 브라우저 언어 자동 감지
```

---

## 10. 예상 작업량

| Phase | 파일 수 | 문자열 수 | 난이도 |
|-------|---------|-----------|--------|
| Phase 1: 인프라 | 4개 신규 + 2개 수정 | ~40 (공통) | 낮음 |
| Phase 2: 핵심 UI | 6개 | 107 | **높음** (humanize.ts) |
| Phase 3: 설정/부가 | 7개 | 86 | 중간 |
| Phase 4: 기타/커넥터 | 10개 | 168 | 낮음 |
| Phase 5: 검증 | 전체 | 누락분 | 중간 |
| **합계** | **29개** | **~600** | — |

---

*작성일: 2026-08-06*
*최종 수정: 2026-08-06 (실측 기반 보완)*
*프로젝트: WeruBWorker GUI i18n*
