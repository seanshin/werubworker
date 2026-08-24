import { describe, expect, it, vi, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { AuditView } from "./AuditView";

// 성능개선 기획서 v2 Phase 5-1 — 감사 로그 목록 가상 스크롤.

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock("./IntegrationsView", () => ({
  PanelHead: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

function events(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `ev-${i}`,
    tool: `tool_${i}`,
    connector: "slack",
    stage: "post",
    status: "ok",
    timestamp: "2026-08-25T00:00:00Z",
    session_id: `s-${i}`,
    resource: `res-${i}`,
    args: { a: 1, b: "two" },
    reason: "because",
  }));
}

async function renderAudit(n: number) {
  vi.mock("../api", () => ({ getAudit: vi.fn() }));
  const api = await import("../api");
  (api.getAudit as any).mockResolvedValue(events(n));
  const view = render(<AuditView />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

afterEach(() => vi.clearAllMocks());

describe("AuditView 가상 스크롤", () => {
  it("작은 목록은 전부 렌더한다", async () => {
    const { container } = await renderAudit(5);
    expect(container.textContent).toContain("tool_4");
  });

  it("150건에서 DOM 노드가 뷰포트를 따른다", async () => {
    const { container } = await renderAudit(150);
    const nodes = container.querySelectorAll("*").length;
    // 카드 하나가 ~9노드라 평면 렌더는 1,300+. 가상화되면 그 근처에도 가지 않는다.
    expect(nodes).toBeLessThan(500);
  });
});
