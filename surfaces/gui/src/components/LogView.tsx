import { useCallback, useEffect, useRef, useState } from "react";

const CARD = "rounded-xl2 border border-line bg-panel";

interface LogEntry {
  ts: number;
  server_id: string;
  line: string;
  severity: string;
  source_id: string;
  matched_pattern: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  error: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
  debug: "#6b7280",
};

function formatTs(epoch: number): string {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString("ko-KR", { hour12: false });
}

export function LogView() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [serverFilter, setServerFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [searchPattern, setSearchPattern] = useState("");
  const [servers, setServers] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (serverFilter) params.set("server_id", serverFilter);
    if (severityFilter) params.set("severity", severityFilter);
    if (searchPattern) params.set("pattern", searchPattern);
    params.set("limit", "500");
    fetch(`/v1/dashboard/logs?${params}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setEntries(d.entries || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [serverFilter, severityFilter, searchPattern]);

  const fetchServers = useCallback(() => {
    fetch("/v1/dashboard/logs/servers")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) setServers(d.servers || []);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchLogs();
    fetchServers();
  }, [fetchLogs, fetchServers]);

  // Auto-refresh every 10s
  useEffect(() => {
    const id = setInterval(fetchLogs, 10_000);
    return () => clearInterval(id);
  }, [fetchLogs]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  const severities = ["", "critical", "error", "warning", "info", "debug"];

  return (
    <div className="flex flex-col h-full gap-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">로그 뷰어</h2>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            자동 스크롤
          </label>
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            {loading ? "로딩..." : "새로고침"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={serverFilter}
          onChange={(e) => setServerFilter(e.target.value)}
          className="text-xs px-2 py-1 rounded border border-line bg-panel"
        >
          <option value="">전체 서버</option>
          {servers.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="text-xs px-2 py-1 rounded border border-line bg-panel"
        >
          {severities.map((s) => (
            <option key={s} value={s}>{s || "전체 심각도"}</option>
          ))}
        </select>
        <input
          type="text"
          value={searchPattern}
          onChange={(e) => setSearchPattern(e.target.value)}
          placeholder="검색 패턴..."
          className="text-xs px-2 py-1 rounded border border-line bg-panel flex-1 min-w-[150px]"
          onKeyDown={(e) => e.key === "Enter" && fetchLogs()}
        />
      </div>

      {/* Log entries */}
      <div
        ref={containerRef}
        className={CARD + " flex-1 overflow-auto p-2 font-mono text-xs leading-5"}
      >
        {entries.length === 0 ? (
          <div className="text-center text-muted py-8">
            {loading ? "로그 로딩 중..." : "로그 데이터가 없습니다"}
          </div>
        ) : (
          entries.map((e, i) => (
            <div
              key={i}
              className="flex gap-2 hover:bg-paper/50 px-1 rounded"
              style={{ borderLeft: `3px solid ${SEVERITY_COLORS[e.severity] || "#6b7280"}` }}
            >
              <span className="text-muted whitespace-nowrap">{formatTs(e.ts)}</span>
              <span className="text-muted whitespace-nowrap">[{e.server_id}]</span>
              <span
                className="font-medium whitespace-nowrap"
                style={{ color: SEVERITY_COLORS[e.severity] || "var(--ink)" }}
              >
                {e.severity?.toUpperCase().padEnd(8)}
              </span>
              <span className="whitespace-pre-wrap break-all">{e.line}</span>
            </div>
          ))
        )}
      </div>

      <div className="text-xs text-muted text-right">
        {entries.length}건 표시
      </div>
    </div>
  );
}
