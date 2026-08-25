import { describe, expect, it, afterEach } from "vitest";
import { cleanup, render, act, screen } from "@testing-library/react";
import i18n from "../i18n";
import { GalleryModal } from "./GalleryModal";

// 클라우드 갤러리가 "사용할 수 없음" 안내로 대체되면서, 그 안내 자체가 하드코딩으로 남았다.

afterEach(async () => {
  cleanup();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

describe("GalleryModal i18n", () => {
  it("영어에서 안내 문구가 렌더된다", () => {
    render(<GalleryModal onClose={() => {}} />);
    expect(screen.getByText("Gallery is not available")).toBeTruthy();
    expect(screen.getByText("Close")).toBeTruthy();
  });

  it("한국어로 전환하면 안내 문구도 번역된다", async () => {
    i18n.addResourceBundle("ko", "settings", {
      gallery: { unavailableTitle: "갤러리를 사용할 수 없습니다" },
    });
    i18n.addResourceBundle("ko", "common", { button: { close: "닫기" } });
    await act(async () => {
      await i18n.changeLanguage("ko");
    });

    render(<GalleryModal onClose={() => {}} />);
    expect(screen.getByText("갤러리를 사용할 수 없습니다")).toBeTruthy();
    expect(screen.getByText("닫기")).toBeTruthy();
    expect(screen.queryByText("Gallery is not available")).toBeNull();
  });
});
