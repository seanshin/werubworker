// 소켓이 붙기 전에 Enter를 치면 메시지가 조용히 사라지던 문제.
//
// Send 버튼은 `disabled={!connected}`로 막혀 있었지만 **키보드 경로는 그 검사를 거치지
// 않았다.** Enter는 `submit()`을 그대로 부르고, `submit()`은 `onSend`를 호출한 뒤 초안을
// 지운다. 그 위쪽에서 `sessionRef.current`가 아직 없거나 이미 닫힌 소켓을 가리키면 메시지는
// 아무 데도 가지 않는데, 사용자 말풍선은 화면에 남는다 — 답이 영영 오지 않는 대화가 된다.
// (E2E 스펙 17개가 이 경합에 걸려 무작위로 실패하던 것을 v2.3.12~13에서 대기로 덮어 뒀다.)
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Composer } from "./Composer";

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

const box = () => screen.getByPlaceholderText(/Ask the coworker/);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("보내기는 소켓이 붙은 뒤에만", () => {
  it("끊긴 동안 Enter는 보내지 않고 초안을 지키지 않는다면 메시지가 사라진다", () => {
    const p = props({ connected: false });
    render(<Composer {...p} />);

    fireEvent.change(box(), { target: { value: "remember the launch date" } });
    fireEvent.keyDown(box(), { key: "Enter" });

    expect(p.onSend).not.toHaveBeenCalled();
    // 초안이 남아 있어야 사용자가 다시 칠 필요가 없다 — 모델 미연결 분기와 같은 원칙이다.
    expect((box() as HTMLTextAreaElement).value).toBe("remember the launch date");
  });

  it("붙고 나면 같은 Enter가 보낸다", () => {
    const p = props({ connected: true });
    render(<Composer {...p} />);

    fireEvent.change(box(), { target: { value: "remember the launch date" } });
    fireEvent.keyDown(box(), { key: "Enter" });

    expect(p.onSend).toHaveBeenCalledWith("remember the launch date", [], undefined);
    expect((box() as HTMLTextAreaElement).value).toBe("");
  });

  it("끊긴 동안 Send 버튼도 여전히 막혀 있다", () => {
    render(<Composer {...props({ connected: false })} />);
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
