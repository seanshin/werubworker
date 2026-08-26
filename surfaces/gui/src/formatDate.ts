import i18n from "./i18n";

// 날짜·시각 표기가 세 갈래로 갈려 있었다: `"ko-KR"` 하드코딩(영어 UI에 한국식 표기가 나갔다),
// 인자 없음(앱이 아니라 **브라우저** 언어를 따라, 한국어 UI가 영어 날짜를 보였다), 그리고 올바른
// `i18n.language`. 표시용 날짜는 전부 여기를 거친다.
//
// 컴포넌트 밖(모듈 수준 함수)에서도 부르므로 훅이 아니라 i18n 인스턴스를 직접 읽는다. 언어를
// 바꾸면 리렌더가 따라오고, 그때 다시 계산된다.
const lng = () => i18n.language || "en";

// `locale`은 대개 생략한다. 가상 스크롤 행처럼 **언어를 prop으로 받아야 다시 렌더되는** 곳에서만
// 넘긴다 — 그런 행은 부모가 리렌더돼도 rowProps가 바뀌지 않으면 옛 표기를 그대로 붙들고 있다.

/** "2026. 8. 26. 09:52" / "Aug 26, 2026, 9:52 AM" */
export function formatDateTime(d: Date | number, opts: Intl.DateTimeFormatOptions = {}, locale?: string): string {
  const date = typeof d === "number" ? new Date(d) : d;
  return date.toLocaleString(locale || lng(), opts);
}

/** 날짜만. */
export function formatDate(d: Date | number, opts: Intl.DateTimeFormatOptions = {}, locale?: string): string {
  const date = typeof d === "number" ? new Date(d) : d;
  return date.toLocaleDateString(locale || lng(), opts);
}

/** 시각만. */
export function formatTime(d: Date | number, opts: Intl.DateTimeFormatOptions = {}, locale?: string): string {
  const date = typeof d === "number" ? new Date(d) : d;
  return date.toLocaleTimeString(locale || lng(), opts);
}

/** 유닉스 초를 받는 곳이 많아 짧은 이름을 따로 둔다. */
export const fromEpoch = (seconds: number) => new Date(seconds * 1000);
