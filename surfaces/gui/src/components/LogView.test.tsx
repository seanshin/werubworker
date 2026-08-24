import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("LogView 가상 스크롤", () => {
  it("작은 목록은 그대로 전부 렌더한다", async () => {
    const { container } = await renderLogs(10);
    expect(screen.getByText(/10건 표시/)).toBeTruthy();
    expect(container.textContent).toContain("some log line 9");
  });

  it("500건에서 DOM 노드가 결과 크기가 아니라 뷰포트를 따른다", async () => {
    const { container } = await renderLogs(500);

    // 카운터는 여전히 전체 건수를 보고한다 — 가상화는 표시일 뿐 자르는 게 아니다.
    expect(screen.getByText(/500건 표시/)).toBeTruthy();

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
