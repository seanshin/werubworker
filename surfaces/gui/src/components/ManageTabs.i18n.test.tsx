import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, act, screen } from "@testing-library/react";
import i18n from "../i18n";
import { ModelsTab } from "./ManageTabs";

// ModelsTab의 문자열은 번역 키가 이미 있는데도 하드코딩돼 있었다. 영어에서는 문구가 같아
// 아무 테스트도 그 사실을 잡지 못했으므로, 한국어로 전환해 배선을 확인한다.

vi.mock("../providers/ProviderSetup", () => ({
  useProviderSetup: () => ({
    sel: "openai",
    info: { title: "OpenAI", configured: true, suggested_models: [] },
    providers: [{ name: "openai" }],
    credentialed: true,
    removeKey: vi.fn(),
  }),
  ProviderCards: () => null,
  ProviderForm: ({ footer }: { footer?: React.ReactNode }) => <div>{footer}</div>,
}));

vi.mock("./ModelChecklist", () => ({ ModelChecklist: () => null }));
vi.mock("./connectors/CloudSignIn", () => ({
  CloudSignInInline: () => null,
  CloudStatusPending: () => null,
}));

vi.mock("../api", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getSettings: vi.fn(async () => ({
    models: [],
    model: "gpt-5",
    model_labels: {},
    source: "stored",
  })),
}));

async function renderTab() {
  const view = render(<ModelsTab />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return view;
}

afterEach(async () => {
  // This repo does not enable testing-library auto-cleanup, so a previous test's tree stays
  // mounted — and re-renders when the language changes, producing duplicate matches.
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("ModelsTab i18n", () => {
  it("영어에서 기존 문구를 그대로 낸다", async () => {
    const { container } = await renderTab();
    expect(container.textContent).toContain("Models");
    expect(container.textContent).toContain("Ticked models show in the composer");
    expect(screen.getByText("Remove key…")).toBeTruthy();
  });

  it("한국어로 전환하면 실제로 번역된다 — 하드코딩이었다면 영어로 남는다", async () => {
    i18n.addResourceBundle("ko", "settings", {
      manageTabs: {
        loading: "로딩 중…",
        models: "모델",
        modelsDesc: "체크된 모델이 입력창 선택기에 표시됩니다.",
        removeKey: "키 제거…",
      },
    });
    await act(async () => {
      await i18n.changeLanguage("ko");
    });

    const { container } = await renderTab();
    expect(container.textContent).toContain("모델");
    expect(container.textContent).toContain("체크된 모델이 입력창 선택기에 표시됩니다.");
    expect(screen.getByText("키 제거…")).toBeTruthy();
    // 영어 원문이 남아 있으면 배선이 빠진 것이다.
    expect(container.textContent).not.toContain("Ticked models show in the composer");
  });
});
