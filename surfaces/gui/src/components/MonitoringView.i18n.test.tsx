import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, act, screen } from "@testing-library/react";
import i18n from "../i18n";
import { MonitoringView } from "./MonitoringView";

// MonitoringView는 useTranslation을 전혀 쓰지 않고 한국어를 하드코딩하고 있었다 —
// 영어로 전환해도 이 화면만 한국어로 남았다. 두 언어 모두에서 확인한다.

vi.mock("../api", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  connectMetrics: () => () => {},
  fetchAnomalies: vi.fn(async () => ({ ok: true, servers: [] })),
  analyzeAnomalies: vi.fn(async () => ({ ok: true })),
  generatePostmortem: vi.fn(async () => ({ ok: true })),
  fetchEscalationPolicies: vi.fn(async () => ({ ok: true, policies: [] })),
}));

vi.stubGlobal(
  "fetch",
  vi.fn(async () => ({ ok: true, json: async () => ({ ok: false }) })),
);

async function renderView() {
  const view = render(<MonitoringView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

afterEach(async () => {
  // auto-cleanup이 꺼져 있어, 남은 트리가 언어 변경 때 함께 다시 렌더되며 중복 매치를 만든다.
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("MonitoringView i18n", () => {
  it("영어에서 제목과 탭이 영문으로 렌더된다", async () => {
    const { container } = await renderView();
    expect(screen.getByText("Monitoring Dashboard")).toBeTruthy();
    for (const tab of ["Dashboard", "Overview", "Alerts", "Incidents", "Health Checks", "Audit Log"]) {
      expect(screen.getByText(tab)).toBeTruthy();
    }
    // 하드코딩이 남아 있으면 한국어가 새어 나온다.
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    i18n.addResourceBundle("ko", "common", {
      monitoring: {
        title: "모니터링 대시보드",
        tab: {
          dashboard: "대시보드", overview: "개요", alerts: "알림",
          incidents: "인시던트", healthchecks: "헬스체크", audit: "감사 로그",
        },
      },
    });
    await act(async () => {
      await i18n.changeLanguage("ko");
    });

    await renderView();
    expect(screen.getByText("모니터링 대시보드")).toBeTruthy();
    expect(screen.getByText("대시보드")).toBeTruthy();
    expect(screen.getByText("감사 로그")).toBeTruthy();
    expect(screen.queryByText("Monitoring Dashboard")).toBeNull();
  });
});
