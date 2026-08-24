"""P3 gate tests — persistent shell executor.

The executor drives the OS-native shell (bash on POSIX, PowerShell on Windows), so the
command strings here are parameterized per-OS. The behavior under test (cwd/env persistence,
exit codes, timeout-and-recover, truncation) is identical across both.
"""

from __future__ import annotations

import sys
import time

import pytest

from coworker.permissions import PermissionEngine
from coworker.tools import ToolRegistry
from coworker.tools.shell import LocalExecutor, shell_tools

_WIN = sys.platform == "win32"

# Per-OS command snippets exercising the same behavior in the native shell.
SET_ENV = "$env:GREETING='hello_world'" if _WIN else "export GREETING=hello_world"
ECHO_ENV = "echo $env:GREETING" if _WIN else "echo $GREETING"
EXIT_OK = "cmd /c exit 0" if _WIN else "true"
EXIT_FAIL = "cmd /c exit 1" if _WIN else "false"
SLEEP_5 = "Start-Sleep -Seconds 5" if _WIN else "sleep 5"
PRINT_1000 = (
    'foreach ($i in 1..1000) { "line$i" }'
    if _WIN
    else "for i in $(seq 1 1000); do echo line$i; done"
)


@pytest.fixture
def executor(tmp_path):
    ex = LocalExecutor(cwd=tmp_path, default_timeout=10)
    yield ex
    ex.close()


def test_cwd_persists_across_calls(executor, tmp_path):
    (tmp_path / "sub").mkdir()
    executor.run("cd sub")
    result = executor.run("pwd")
    assert result["exit_code"] == 0
    assert "sub" in result["output"]
    assert executor.cwd.endswith("sub")


def test_env_persists_across_calls(executor):
    executor.run(SET_ENV)
    result = executor.run(ECHO_ENV)
    assert "hello_world" in result["output"]


def test_exit_code_captured(executor):
    assert executor.run(EXIT_OK)["exit_code"] == 0
    assert executor.run(EXIT_FAIL)["exit_code"] == 1


def test_timeout_kills_command(executor):
    start = time.monotonic()
    result = executor.run(SLEEP_5, timeout=1)
    elapsed = time.monotonic() - start
    assert result["timed_out"] is True
    assert elapsed < 4.0  # did not block for the full sleep
    # session survives the timeout — still usable (POSIX keeps the shell; Windows respawns)
    assert executor.run("echo alive")["output"].strip().endswith("alive")


def test_large_output_truncated_keeps_tail(tmp_path):
    ex = LocalExecutor(cwd=tmp_path, max_output_chars=200, default_timeout=10)
    try:
        result = ex.run(PRINT_1000)
        assert result["truncated"] is True
        assert len(result["output"]) <= 200
        # the END survives (where test/build verdicts live), the head is dropped
        assert "line1000" in result["output"]
        assert "line1\n" not in result["output"]
    finally:
        ex.close()


def test_shell_tool_integration(executor, tmp_path):
    reg = ToolRegistry()
    reg.register_all(shell_tools(executor))
    assert {"run_shell", "shell_task_output", "shell_task_kill"} <= set(reg.names())

    spec = reg.get("run_shell")
    assert spec.metadata.requires_approval is True
    # polling/killing the agent's own background tasks doesn't need approval
    assert reg.get("shell_task_output").metadata.requires_approval is False
    assert reg.get("shell_task_kill").metadata.requires_approval is False

    eng = PermissionEngine(workspace_root=tmp_path)
    decision = eng.evaluate("run_shell", {"command": "echo hi"}, spec.metadata)
    assert not decision.allowed and decision.needs_user  # high-risk → asks

    out = reg.execute("run_shell", {"command": "echo hi"})
    assert "hi" in out["output"]


def test_run_shell_accepts_description_and_clamped_timeout(executor):
    reg = ToolRegistry()
    reg.register_all(shell_tools(executor))
    # `description` rides along for approval prompts/audit; it must not break execution.
    out = reg.execute(
        "run_shell",
        {"command": "echo ok", "description": "Say ok", "timeout_seconds": 99999},
    )
    assert out["exit_code"] == 0 and "ok" in out["output"]


# -- background tasks ------------------------------------------------------------

ECHO_THEN_SLEEP = (
    "Write-Output started; Start-Sleep -Seconds 30" if _WIN else "echo started; sleep 30"
)
QUICK_ECHO = "Write-Output quick_done" if _WIN else "echo quick_done"


def _poll_output(reg, task_id, *, until_status=None, deadline=10.0):
    """Poll shell_task_output, accumulating output until a status is reached."""
    acc = ""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        res = reg.execute("shell_task_output", {"task_id": task_id})
        acc += res["output"]
        if until_status is None or res["status"] == until_status:
            if until_status is None and not acc:
                time.sleep(0.1)
                continue
            return acc, res
        time.sleep(0.1)
    return acc, res


def test_background_task_runs_and_exits(executor):
    reg = ToolRegistry()
    reg.register_all(shell_tools(executor))
    started = reg.execute("run_shell", {"command": QUICK_ECHO, "run_in_background": True})
    assert started["status"] == "running" and started["task_id"]

    acc, res = _poll_output(reg, started["task_id"], until_status="exited")
    assert res["status"] == "exited"
    assert res["exit_code"] == 0
    assert "quick_done" in acc

    # output reads are incremental: a second read returns nothing new
    again = reg.execute("shell_task_output", {"task_id": started["task_id"]})
    assert again["output"] == ""


def test_background_task_kill(executor):
    reg = ToolRegistry()
    reg.register_all(shell_tools(executor))
    started = reg.execute("run_shell", {"command": ECHO_THEN_SLEEP, "run_in_background": True})
    acc, _ = _poll_output(reg, started["task_id"])
    assert "started" in acc  # it's alive and producing output

    killed = reg.execute("shell_task_kill", {"task_id": started["task_id"]})
    assert killed["status"] == "killed"

    res = reg.execute("shell_task_output", {"task_id": started["task_id"]})
    assert res["status"] == "exited"


def test_background_unknown_task_errors(executor):
    reg = ToolRegistry()
    reg.register_all(shell_tools(executor))
    assert "unknown task" in reg.execute("shell_task_output", {"task_id": "bg-99"})["error"]
    assert "unknown task" in reg.execute("shell_task_kill", {"task_id": "bg-99"})["error"]


# -- background task memory bounds (성능개선 기획서 v2 Phase 6-1) ------------------


@pytest.mark.skipif(_WIN, reason="uses a POSIX loop to generate bulk output")
def test_background_buffer_is_bounded(executor):
    """A chatty background task must not grow its buffer without limit.

    The reader thread drains the child's stdout for the life of the process, so before this
    was bounded one `tail -f`-shaped command held every line it ever emitted — measured at
    15.8 MB for 200k lines, retained even after the process exited and the output was read."""
    from coworker.tools.shell import _BG_MAX_CHARS, _BG_MAX_LINES

    started = executor.run_background("for i in $(seq 1 50000); do echo \"line $i padding\"; done")
    task = executor._bg_tasks[started["task_id"]]
    for _ in range(100):
        if task.proc.poll() is not None:
            break
        time.sleep(0.1)

    assert len(task._lines) <= _BG_MAX_LINES
    assert task._chars <= _BG_MAX_CHARS
    # The task really did produce far more than it kept — otherwise this proves nothing.
    assert task._appended > _BG_MAX_LINES * 5


@pytest.mark.skipif(_WIN, reason="uses a POSIX loop to generate bulk output")
def test_background_output_reports_dropped_lines(executor):
    """Evicted output is gone, and the caller is told rather than shown a silent gap."""
    started = executor.run_background("for i in $(seq 1 50000); do echo \"line $i padding\"; done")
    task = executor._bg_tasks[started["task_id"]]
    for _ in range(100):
        if task.proc.poll() is not None:
            break
        time.sleep(0.1)

    res = executor.background_output(started["task_id"])
    assert res["dropped_lines"] > 0
    assert "scrolled out" in res["note"]
    # The tail survived: the last line the command emitted is still readable.
    assert "line 50000" in res["output"]

    # And the drop counter resets — the next read is not re-reported.
    assert "dropped_lines" not in executor.background_output(started["task_id"])


def test_background_reads_stay_incremental_across_eviction(executor):
    """The read cursor is an absolute line count, not a deque index.

    An index-based cursor silently re-reads or skips lines once eviction starts, which is
    worse than dropping them: the caller sees plausible output that never happened."""
    from coworker.tools.shell import _BackgroundTask

    task = _BackgroundTask.__new__(_BackgroundTask)  # no child process needed
    import threading
    from collections import deque

    task._lock = threading.Lock()
    task._lines = deque()
    task._chars = 0
    task._appended = 0
    task._cursor = 0
    task._dropped_unread = 0

    def emit(text):
        with task._lock:
            task._lines.append(text)
            task._chars += len(text)
            task._appended += 1
            task._evict()

    import coworker.tools.shell as shell_mod

    original = shell_mod._BG_MAX_LINES
    shell_mod._BG_MAX_LINES = 3
    try:
        for i in range(3):
            emit(f"{i}\n")
        assert task.read_new() == ("0\n1\n2\n", 0)

        # Overflow past the cap while nothing is read: the oldest lines are evicted.
        for i in range(3, 9):
            emit(f"{i}\n")
        text, dropped = task.read_new()
        # Exactly the retained tail, each line once, in order — no repeats from index reuse.
        assert text == "6\n7\n8\n"
        assert dropped == 3  # lines 3,4,5 evicted unread
        assert task.read_new() == ("", 0)

        # Reads stay incremental after eviction.
        emit("9\n")
        assert task.read_new() == ("9\n", 0)
    finally:
        shell_mod._BG_MAX_LINES = original


@pytest.mark.skipif(_WIN, reason="POSIX shell command")
def test_finished_background_tasks_are_reaped(executor):
    """Finished tasks must not accumulate for the life of the session."""
    from coworker.tools.shell import _BG_KEEP_FINISHED

    ids = []
    for _ in range(_BG_KEEP_FINISHED + 5):
        started = executor.run_background("echo done")
        ids.append(started["task_id"])
        for _ in range(50):
            if executor._bg_tasks[ids[-1]].proc.poll() is not None:
                break
            time.sleep(0.05)

    # One more start triggers the reap of everything past the retention window.
    executor.run_background("echo done")
    assert len(executor._bg_tasks) <= _BG_KEEP_FINISHED + 1

    # The oldest are gone and say so; the most recent stay readable.
    assert "unknown task" in executor.background_output(ids[0])["error"]
    assert "error" not in executor.background_output(ids[-1])


@pytest.mark.skipif(_WIN, reason="POSIX shell command")
def test_running_background_tasks_are_never_reaped(executor):
    """Reaping frees memory; it must not kill a dev server the user is relying on."""
    from coworker.tools.shell import _BG_KEEP_FINISHED

    long_running = executor.run_background("sleep 30")
    try:
        for _ in range(_BG_KEEP_FINISHED + 5):
            started = executor.run_background("echo done")
            for _ in range(50):
                if executor._bg_tasks.get(started["task_id"]) is None:
                    break
                if executor._bg_tasks[started["task_id"]].proc.poll() is not None:
                    break
                time.sleep(0.05)
        executor.run_background("echo done")

        assert long_running["task_id"] in executor._bg_tasks
        assert executor._bg_tasks[long_running["task_id"]].proc.poll() is None
    finally:
        executor.background_kill(long_running["task_id"])
