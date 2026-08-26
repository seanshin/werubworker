import type { TFunction } from "i18next";
import type { ScheduleDesc } from "./api";
import { formatTime } from "./formatDate";

// 서버는 일정을 **영어 한 줄**로도 보내고(`schedule` — 에이전트와 Slack 봇이 읽는다),
// 조각으로도 보낸다(`schedule_desc`). 화면 문구는 여기서 사용자 언어로 만든다.
//
// `schedule_desc`가 없는 응답(구버전 서버)에서는 영어 한 줄로 되돌아간다 — 번역은 못 하지만
// 빈 칸을 보여주는 것보다 낫다.
export function scheduleLabel(t: TFunction, desc: ScheduleDesc | undefined, fallback: string): string {
  if (!desc) return fallback;

  // 시각은 로케일이 정한다: 영어는 "5:40 PM", 한국어는 "오후 5:40".
  const at = (d: ScheduleDesc) =>
    formatTime(new Date(2000, 0, 1, d.hour ?? 0, d.minute ?? 0), {
      hour: "numeric",
      minute: "2-digit",
    });

  switch (desc.kind) {
    case "daily":
      return t("session:schedule.daily", { time: at(desc) });
    case "weekly":
      return t("session:schedule.weekly", {
        day: t(`session:schedule.dow.${(desc.dow ?? 0) % 7}`),
        time: at(desc),
      });
    case "monthly":
      return t("session:schedule.monthly", { dom: desc.dom, time: at(desc) });
    case "once":
      return t("session:schedule.once", { when: desc.fire_at ?? "" });
    default:
      // 범위·스텝이 섞인 cron은 번역할 문장이 없다 — 원본을 그대로 보여준다.
      return desc.cron || fallback;
  }
}

/** 실행 상태는 서버가 코드로 보낸다(`running` | `ok` | `error` | `skipped`). 모르는 값이 오면
 * 그대로 보여준다 — 새 상태가 생겨도 빈 칸이 나가지 않는다. */
export function runStatus(t: TFunction, status: string | null | undefined): string {
  if (!status) return "";
  return t(`session:schedule.runStatus.${status}`, { defaultValue: status });
}
