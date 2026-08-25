import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, act } from "@testing-library/react";
import i18n from "../i18n";
import { LogView } from "./LogView";

// 성능개선 기획서 v2 Phase 5-1 — 로그 뷰어 가상 스크롤.

function makeEntries(n: number, line = "some log line") {
  return Array.from({ length: n }, (_, i) => ({
    ts: 1700000000 + i,
    server_id: "srv-1",
    line: `${line} ${i}`,
    severity: i % 2 ? "error" : "info",
    source_id: "s",
    matched_pattern: "",
  }));
}

function mockLogs(entries: any[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            String(url).includes("/logs/servers")
              ? { ok: true, servers: ["srv-1"] }
              : { ok: true, entries }
          ),
      })
    )
  );
}

async function renderLogs(n: number) {
  mockLogs(makeEntries(n));
  const view = render(<LogView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(async () => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  // auto-cleanup이 꺼져 있어, 남은 트리가 언어 변경 때 함께 다시 렌더된다.
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("LogView 가상 스크롤", () => {
  it("작은 목록은 그대로 전부 렌더한다", async () => {
    const { container } = await renderLogs(10);
    expect(screen.getByText(/10 shown/)).toBeTruthy();
    expect(container.textContent).toContain("some log line 9");
  });

  it("500건에서 DOM 노드가 결과 크기가 아니라 뷰포트를 따른다", async () => {
    const { container } = await renderLogs(500);

    // 카운터는 여전히 전체 건수를 보고한다 — 가상화는 표시일 뿐 자르는 게 아니다.
    expect(screen.getByText(/500 shown/)).toBeTruthy();

    const nodes = container.querySelectorAll("*").length;
    // 평면 렌더는 행당 5노드 × 500 = 2,500+. 가상화되면 그 근처에도 가지 않는다.
    expect(nodes).toBeLessThan(700);
  });

  it("가상 경로와 평면 경로가 같은 마크업을 낸다", async () => {
    const small = await renderLogs(3);
    const smallRow = small.container.querySelector(".flex.gap-2.hover\\:bg-paper\\/50");
    expect(smallRow).toBeTruthy();
    small.unmount();

    const big = await renderLogs(500);
    const bigRow = big.container.querySelector(".flex.gap-2.hover\\:bg-paper\\/50");
    expect(bigRow).toBeTruthy();
    // 같은 컴포넌트를 쓰므로 자식 구성(타임스탬프/서버/심각도/본문)이 동일하다.
    expect(bigRow!.children.length).toBe(smallRow!.children.length);
  });

  it("긴 로그 줄의 줄바꿈 동작을 유지한다", async () => {
    mockLogs(makeEntries(500, "x".repeat(400)));
    const { container } = render(<LogView />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // 고정 행 높이로 바꾸면서 nowrap으로 돌리지 않았는지 — 로그 본문은 계속 감싸야 한다.
    const body = container.querySelector(".whitespace-pre-wrap");
    expect(body).toBeTruthy();
  });
});

// LogView도 useTranslation을 쓰지 않고 한국어를 하드코딩하고 있었다 — 영어로 전환해도
// 이 화면만 한국어로 남았다.
describe("LogView i18n", () => {
  it("영어에서 한글이 새어 나오지 않는다", async () => {
    const { container } = await renderLogs(3);
    expect(screen.getByText("Log Viewer")).toBeTruthy();
    expect(screen.getByText("All servers")).toBeTruthy();
    expect(container.textContent).not.toMatch(/[가-힣]/);
  });

  it("한국어로 전환하면 한국어로 렌더된다", async () => {
    i18n.addResourceBundle("ko", "common", {
      monitoring: {
        log: { title: "로그 뷰어", allServers: "전체 서버", refresh: "새로고침" },
      },
    });
    await act(async () => {
      await i18n.changeLanguage("ko");
    });

    await renderLogs(3);
    expect(screen.getByText("로그 뷰어")).toBeTruthy();
    expect(screen.getByText("전체 서버")).toBeTruthy();
    expect(screen.queryByText("Log Viewer")).toBeNull();
  });
});
