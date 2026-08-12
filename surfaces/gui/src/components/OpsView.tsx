import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";
import { MiniChart } from "./MiniChart";
import { ProgressBar } from "./ProgressBar";
import { connectEvents } from "../api";

const CARD = "rounded-xl2 border border-line bg-panel";

const POLL_INTERVAL_MS = 10_000;
const MAX_HISTORY = 30;

interface SshServer {
  id?: string;
  server_id?: string;
  name?: string;
  host: string;
  port?: number;
  user?: string;
  username?: string;
  status?: string;
  label?: string;
}

interface AlertInfo {
  metric: string;
  value: number;
  threshold: number;
}

interface DiskPartition {
  device: string;
  mountpoint: string;
  fstype: string;
  total_gb: number;
  used_gb: number;
  free_gb: number;
  percent: number;
}

interface ServerStatus {
  cpu_percent?: number;
  cpu_count?: number;
  cpu_count_logical?: number;
  cpu_freq_mhz?: number;
  cpu_per_core?: number[];
  cpu_times?: { user: number; system: number; idle: number };
  load_avg?: { "1m": number; "5m": number; "15m": number };
  memory?: { percent?: number; total_gb?: number; available_gb?: number; used_gb?: number };
  swap?: { total_gb?: number; used_gb?: number; percent?: number };
  disk_root?: { percent?: number; total_gb?: number; used_gb?: number };
  disk_partitions?: DiskPartition[];
  uptime_seconds?: number;
  docker_containers?: { name: string; status: string; image: string }[];
  alerts?: AlertInfo[];
  /* fallback fields from the existing simulated format */
  cpu?: number;
  disk?: number;
  logs?: string[];
}

interface ProcessInfo {
  pid: number;
  name: string;
  cpu_percent?: number;
  memory_percent?: number;
  status?: string;
  cmdline?: string;
  create_time?: number;
  num_threads?: number;
  username?: string;
}

interface NetworkInterface {
  bytes_sent: number;
  bytes_recv: number;
  packets_sent: number;
  packets_recv: number;
  errin: number;
  errout: number;
  dropin?: number;
  dropout?: number;
  addresses?: { family: string; address: string }[];
  is_up?: boolean;
  speed_mbps?: number;
  mtu?: number;
}

interface NetworkStats {
  ok: boolean;
  interfaces?: Record<string, NetworkInterface>;
  connections?: number;
  total?: { bytes_sent: number; bytes_recv: number; packets_sent: number; packets_recv: number };
  error?: string;
}

interface HealthCheck {
  type: string;
  target: string;
  last_status: string;
  last_check: number;
}

interface PortStatus {
  port: number;
  status: string;
}

interface DockerContainer {
  ID?: string;
  Names?: string;
  Image?: string;
  Status?: string;
  State?: string;
  Ports?: string;
}

interface MetricPoint {
  timestamp: number;
  cpu: number;
  memory: number;
  disk: number;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

/** Extract a 0-100 CPU value from either real or simulated status. */
function cpuOf(s: ServerStatus): number {
  return Math.round(s.cpu_percent ?? s.cpu ?? 0);
}
function memOf(s: ServerStatus): number {
  return Math.round(s.memory?.percent ?? (s as any).memory ?? 0);
}
function diskOf(s: ServerStatus): number {
  return Math.round(s.disk_root?.percent ?? s.disk ?? 0);
}

function serverId(s: SshServer): string {
  return s.server_id || s.id || s.host;
}

// ---------------------------------------------------------------------------
// SSH Server Modal
// ---------------------------------------------------------------------------
function SshModal({
  server,
  onClose,
  onSaved,
}: {
  server: SshServer | null; // null = add mode
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation(["session", "common"]);
  const isEdit = server !== null;
  const [host, setHost] = useState(server?.host ?? "");
  const [port, setPort] = useState(server?.port ?? 22);
  const [username, setUsername] = useState(server?.username ?? server?.user ?? "deploy");
  const [sId, setSId] = useState(isEdit ? serverId(server!) : "");
  const [label, setLabel] = useState(server?.label ?? server?.name ?? "");
  const [keyPath, setKeyPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [error, setError] = useState("");

  const handleTest = async () => {
    if (!host.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      // For testing we need a saved server; for new ones, just skip
      if (isEdit) {
        const r = await fetch(`/v1/ssh/servers/${encodeURIComponent(serverId(server!))}/test`, { method: "POST" });
        const d = await r.json();
        setTestResult(d.ok ? "ok" : d.error || "failed");
      } else {
        setTestResult("save first");
      }
    } catch {
      setTestResult("error");
    }
    setTesting(false);
  };

  const handleSave = async () => {
    if (!host.trim()) { setError("Host is required"); return; }
    if (!sId.trim() && !isEdit) { setError("Server ID is required"); return; }
    setSaving(true);
    setError("");
    try {
      const body = { server_id: sId.trim(), host: host.trim(), port, username: username.trim(), label: label.trim(), key_path: keyPath.trim(), tags: [] };
      const url = isEdit ? `/v1/ssh/servers/${encodeURIComponent(serverId(server!))}` : "/v1/ssh/servers";
      const method = isEdit ? "PUT" : "POST";
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      if (d.ok) { onSaved(); onClose(); }
      else setError(d.error || "Save failed");
    } catch { setError("Network error"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-panel rounded-xl2 border border-line p-6 w-[420px] max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-semibold text-ink mb-4">
          {isEdit ? t("session:ops.editServer") : t("session:ops.addServer")}
        </h3>
        <div className="space-y-3">
          {!isEdit && (
            <Field label="Server ID" value={sId} onChange={setSId} placeholder="web-01" />
          )}
          <Field label="Host" value={host} onChange={setHost} placeholder="192.168.1.10" />
          <div className="flex gap-3">
            <div className="flex-1">
              <Field label="Port" value={String(port)} onChange={(v) => setPort(Number(v) || 22)} type="number" />
            </div>
            <div className="flex-1">
              <Field label="Username" value={username} onChange={setUsername} placeholder="deploy" />
            </div>
          </div>
          <Field label="Label" value={label} onChange={setLabel} placeholder="Production Web" />
          <Field label="Key Path" value={keyPath} onChange={setKeyPath} placeholder="~/.ssh/id_ed25519" />
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        {testResult && (
          <p className={"text-[12px] mt-2 " + (testResult === "ok" ? "text-ok" : "text-err")}>
            {testResult === "ok" ? "Connection successful" : testResult}
          </p>
        )}
        <div className="flex justify-between mt-5">
          <button className="text-[13px] text-muted hover:text-ink" onClick={handleTest} disabled={testing}>
            {testing ? "Testing..." : "Test Connection"}
          </button>
          <div className="flex gap-2">
            <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={onClose}>
              {t("common:button.cancel")}
            </button>
            <button
              className="text-[13px] px-3 py-1.5 rounded-lg bg-accent text-white font-medium"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? "Saving..." : t("common:button.save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-[12px] text-muted mb-1">{label}</label>
      <input
        type={type || "text"}
        className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delete Confirmation
// ---------------------------------------------------------------------------
function DeleteConfirm({ name, onConfirm, onCancel }: {
  name: string; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={onCancel}>
      <div className="bg-panel rounded-xl2 border border-line p-5 w-[340px]" onClick={(e) => e.stopPropagation()}>
        <p className="text-[14px] text-ink mb-4">Delete server <strong>{name}</strong>?</p>
        <div className="flex justify-end gap-2">
          <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={onCancel}>Cancel</button>
          <button className="text-[13px] px-3 py-1.5 rounded-lg bg-err text-white font-medium" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
export function OpsView() {
  const { t } = useTranslation(["session", "common"]);
  const [servers, setServers] = useState<SshServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [localStatus, setLocalStatus] = useState<ServerStatus | null>(null);
  const [polling, setPolling] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Metric history (last MAX_HISTORY samples)
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [memHistory, setMemHistory] = useState<number[]>([]);
  const [diskHistory, setDiskHistory] = useState<number[]>([]);

  // SSH modal state
  const [sshModal, setSshModal] = useState<{ open: boolean; server: SshServer | null }>({ open: false, server: null });
  const [deleteTarget, setDeleteTarget] = useState<SshServer | null>(null);

  // Processes & Ports
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [ports, setPorts] = useState<PortStatus[]>([]);
  const [processFilter, setProcessFilter] = useState("");
  const [activeTab, setActiveTab] = useState<"status" | "processes" | "ports" | "docker" | "network" | "health">("status");

  // Process sorting
  const [procSortKey, setProcSortKey] = useState<"cpu_percent" | "memory_percent" | "pid" | "name">("cpu_percent");
  const [procSortAsc, setProcSortAsc] = useState(false);

  // Kill confirmation
  const [killTarget, setKillTarget] = useState<ProcessInfo | null>(null);
  const [killing, setKilling] = useState(false);

  // Network stats (S11)
  const [networkStats, setNetworkStats] = useState<NetworkStats | null>(null);
  const [networkLoading, setNetworkLoading] = useState(false);

  // Health checks (S12)
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [, setHealthEnabled] = useState(false);
  const [healthRunning, setHealthRunning] = useState(false);
  const [newCheckType, setNewCheckType] = useState("port");
  const [newCheckTarget, setNewCheckTarget] = useState("");

  // Alert state (Step 5)
  const [alerts, setAlerts] = useState<AlertInfo[]>([]);
  const [alertThresholds, setAlertThresholds] = useState({ cpu: 90, memory: 85, disk: 90 });
  const [showAlertSettings, setShowAlertSettings] = useState(false);
  const [savingThresholds, setSavingThresholds] = useState(false);

  // Docker state (Step 6)
  const [dockerContainers, setDockerContainers] = useState<DockerContainer[]>([]);
  const [dockerLoading, setDockerLoading] = useState(false);
  const [dockerLogs, setDockerLogs] = useState<{ id: string; logs: string } | null>(null);
  const [dockerActionLoading, setDockerActionLoading] = useState<string | null>(null);

  // Metrics history (Step 7)
  const [metricsRange, setMetricsRange] = useState<"1h" | "6h" | "24h" | "7d">("1h");
  const [metricsHistory, setMetricsHistory] = useState<MetricPoint[]>([]);

  const fetchServers = useCallback(() => {
    setLoading(true);
    fetch("/v1/ssh/servers")
      .then((r) => (r.ok ? r.json() : { servers: [] }))
      .then((data) => {
        const list = Array.isArray(data) ? data : Array.isArray(data?.servers) ? data.servers : [];
        setServers(list);
        setFetchError(null);
      })
      .catch((e) => { setServers([]); setFetchError(e.message); })
      .finally(() => setLoading(false));
  }, []);

  const fetchStatus = useCallback(() => {
    fetch("/v1/ops/local-status")
      .then((r) => {
        if (!r.ok) throw new Error("fetch failed");
        return r.json();
      })
      .then((data: ServerStatus) => {
        setLocalStatus(data);
        setCpuHistory((prev) => [...prev, cpuOf(data)].slice(-MAX_HISTORY));
        setMemHistory((prev) => [...prev, memOf(data)].slice(-MAX_HISTORY));
        setDiskHistory((prev) => [...prev, diskOf(data)].slice(-MAX_HISTORY));
        if (data.alerts && data.alerts.length > 0) {
          setAlerts(data.alerts);
        }
      })
      .catch(() => { /* endpoint may not exist yet */ });
  }, []);

  const fetchProcesses = useCallback(() => {
    fetch(`/v1/ops/processes?filter=${encodeURIComponent(processFilter)}`)
      .then((r) => r.ok ? r.json() : { processes: [] })
      .then((d) => setProcesses(d.processes || d.rows || []))
      .catch(() => {});
  }, [processFilter]);

  const fetchPorts = useCallback(() => {
    fetch("/v1/ops/ports")
      .then((r) => r.ok ? r.json() : { ports: [] })
      .then((d) => setPorts(d.ports || d.results || []))
      .catch(() => {});
  }, []);

  const fetchAlertConfig = useCallback(() => {
    fetch("/v1/ops/alerts/config")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.thresholds) setAlertThresholds(d.thresholds); })
      .catch(() => {});
  }, []);

  const saveAlertConfig = useCallback(async () => {
    setSavingThresholds(true);
    try {
      const r = await fetch("/v1/ops/alerts/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(alertThresholds),
      });
      const d = await r.json();
      if (d?.thresholds) setAlertThresholds(d.thresholds);
    } catch { /* ignore */ }
    setSavingThresholds(false);
  }, [alertThresholds]);

  const fetchDockerContainers = useCallback(() => {
    setDockerLoading(true);
    fetch("/v1/docker/containers?all=true")
      .then((r) => r.ok ? r.json() : { containers: [] })
      .then((d) => setDockerContainers(d.containers || []))
      .catch(() => setDockerContainers([]))
      .finally(() => setDockerLoading(false));
  }, []);

  const dockerAction = useCallback(async (containerId: string, action: string) => {
    setDockerActionLoading(containerId);
    try {
      await fetch(`/v1/docker/containers/${encodeURIComponent(containerId)}/${action}`, { method: "POST" });
      // Refresh after action
      setTimeout(fetchDockerContainers, 1000);
    } catch { /* ignore */ }
    setDockerActionLoading(null);
  }, [fetchDockerContainers]);

  const fetchDockerLogs = useCallback(async (containerId: string) => {
    try {
      const r = await fetch(`/v1/docker/containers/${encodeURIComponent(containerId)}/logs?tail=100`);
      const d = await r.json();
      setDockerLogs({ id: containerId, logs: d.logs || d.error || "No logs" });
    } catch {
      setDockerLogs({ id: containerId, logs: "Failed to fetch logs" });
    }
  }, []);

  const fetchMetricsHistory = useCallback(() => {
    fetch(`/v1/ops/metrics?range=${metricsRange}`)
      .then((r) => r.ok ? r.json() : { metrics: [] })
      .then((d) => setMetricsHistory(d.metrics || []))
      .catch(() => setMetricsHistory([]));
  }, [metricsRange]);

  const killProcess = useCallback(async (pid: number, signal: string = "TERM") => {
    setKilling(true);
    try {
      await fetch(`/v1/ops/processes/${pid}/kill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signal }),
      });
      setTimeout(fetchProcesses, 500);
    } catch { /* ignore */ }
    setKilling(false);
    setKillTarget(null);
  }, [fetchProcesses]);

  const fetchNetworkStats = useCallback(() => {
    setNetworkLoading(true);
    fetch("/v1/ops/network")
      .then((r) => r.ok ? r.json() : { ok: false, error: "fetch failed" })
      .then((d) => setNetworkStats(d))
      .catch(() => setNetworkStats({ ok: false, error: "Network error" }))
      .finally(() => setNetworkLoading(false));
  }, []);

  const fetchHealthChecks = useCallback(() => {
    fetch("/v1/ops/healthcheck")
      .then((r) => r.ok ? r.json() : { checks: [] })
      .then((d) => {
        setHealthChecks(d.checks || []);
        setHealthEnabled(d.enabled ?? false);
      })
      .catch(() => {});
  }, []);

  const runHealthChecks = useCallback(async () => {
    setHealthRunning(true);
    try {
      const r = await fetch("/v1/ops/healthcheck/run", { method: "POST" });
      const d = await r.json();
      if (d.results) setHealthChecks(d.results);
    } catch { /* ignore */ }
    setHealthRunning(false);
  }, []);

  const addHealthCheck = useCallback(async () => {
    if (!newCheckTarget.trim()) return;
    try {
      const r = await fetch("/v1/ops/healthcheck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: newCheckType, target: newCheckTarget.trim() }),
      });
      const d = await r.json();
      if (d.checks) setHealthChecks(d.checks);
      setNewCheckTarget("");
    } catch { /* ignore */ }
  }, [newCheckType, newCheckTarget]);

  // Listen for server_alert events via WS
  useEffect(() => {
    const stop = connectEvents((msg) => {
      if (msg.type !== "server_alert") return;
      // alerts may be at msg.alerts (raw broadcast) or msg.data.alerts
      const raw = msg as Record<string, any>;
      const a = raw.alerts ?? raw.data?.alerts;
      if (Array.isArray(a) && a.length > 0) setAlerts(a);
    });
    return stop;
  }, []);

  useEffect(() => { fetchServers(); fetchAlertConfig(); }, [fetchServers, fetchAlertConfig]);

  useEffect(() => {
    fetchStatus();
    if (polling) {
      timerRef.current = setInterval(fetchStatus, POLL_INTERVAL_MS);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchStatus, polling]);

  // Fetch processes/ports/docker/network/health when tab changes
  useEffect(() => {
    if (activeTab === "processes") fetchProcesses();
    if (activeTab === "ports") fetchPorts();
    if (activeTab === "docker") fetchDockerContainers();
    if (activeTab === "network") fetchNetworkStats();
    if (activeTab === "health") fetchHealthChecks();
  }, [activeTab, fetchProcesses, fetchPorts, fetchDockerContainers, fetchNetworkStats, fetchHealthChecks]);

  // Fetch metrics history when range changes
  useEffect(() => {
    fetchMetricsHistory();
  }, [fetchMetricsHistory]);

  const handleDeleteServer = async (s: SshServer) => {
    const id = serverId(s);
    try {
      await fetch(`/v1/ssh/servers/${encodeURIComponent(id)}`, { method: "DELETE" });
    } catch { /* ignore */ }
    setDeleteTarget(null);
    fetchServers();
  };

  const sortedProcesses = [...processes].sort((a, b) => {
    const dir = procSortAsc ? 1 : -1;
    if (procSortKey === "name") {
      return dir * (a.name || "").localeCompare(b.name || "");
    }
    const av = (a as any)[procSortKey] ?? 0;
    const bv = (b as any)[procSortKey] ?? 0;
    return dir * (av - bv);
  });

  const toggleProcSort = (key: typeof procSortKey) => {
    if (procSortKey === key) setProcSortAsc((v) => !v);
    else { setProcSortKey(key); setProcSortAsc(false); }
  };

  const cpu = localStatus ? cpuOf(localStatus) : 0;
  const mem = localStatus ? memOf(localStatus) : 0;
  const disk = localStatus ? diskOf(localStatus) : 0;
  const containers = localStatus?.docker_containers;

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:ops.title")}
            sub={t("session:ops.sub")}
          />

          {/* Error banner */}
          {fetchError && (
            <div className="mb-4 px-4 py-2.5 rounded-lg bg-err/10 text-err text-[13px]">
              {t("session:ops.fetchError")}: {fetchError}
            </div>
          )}

          {/* Alert banner (Step 5) */}
          {alerts.length > 0 && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-err/10 border border-err/30">
              <div className="flex items-center gap-2 mb-1">
                <Icon name="info" size={15} className="text-err shrink-0" />
                <span className="text-[13px] font-semibold text-err">{t("session:ops.alertTitle")}</span>
              </div>
              <div className="space-y-1">
                {alerts.map((a, i) => (
                  <div key={i} className="text-[12.5px] text-err/80">
                    {t("session:ops.alertMessage", {
                      metric: a.metric.toUpperCase(),
                      value: Math.round(a.value),
                      threshold: Math.round(a.threshold),
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab bar */}
          <div className="flex gap-1 mb-4 flex-wrap">
            {(["status", "processes", "ports", "docker", "network", "health"] as const).map((tab) => (
              <button
                key={tab}
                className={
                  "text-[13px] px-3 py-1.5 rounded-lg font-medium " +
                  (activeTab === tab ? "bg-accent/10 text-accent" : "text-muted hover:text-ink")
                }
                onClick={() => setActiveTab(tab)}
              >
                {tab === "status" ? t("session:ops.localStatus") :
                 tab === "processes" ? t("session:ops.processes") :
                 tab === "ports" ? t("session:ops.ports") :
                 tab === "docker" ? t("session:ops.docker") :
                 tab === "network" ? t("session:ops.network") :
                 t("session:ops.healthChecks")}
              </button>
            ))}
          </div>

          {/* STATUS TAB */}
          {activeTab === "status" && (
            <>
              {/* Local server status with sparklines */}
              <div className={CARD + " p-5 mb-4"}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-[14px] font-semibold text-ink">
                    {t("session:ops.localStatus")}
                  </h3>
                  <button
                    className={
                      "text-[12px] px-2.5 py-1.5 rounded-lg border border-line " +
                      (polling ? "text-ok bg-ok/5" : "text-muted bg-paper")
                    }
                    onClick={() => setPolling((p) => !p)}
                  >
                    {t("session:ops.autoRefresh", { seconds: POLL_INTERVAL_MS / 1000 })}
                  </button>
                </div>

                {localStatus ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-4">
                      <div className="flex-1 min-w-0"><ProgressBar label="CPU" value={cpu} /></div>
                      <MiniChart data={cpuHistory} type="line" height={28} width={120} color="var(--accent)" />
                    </div>

                    {/* CPU per-core bars */}
                    {localStatus.cpu_per_core && localStatus.cpu_per_core.length > 0 && (
                      <div>
                        <div className="text-[11.5px] text-muted mb-2">{t("session:ops.cpuPerCore")}</div>
                        <div className="flex gap-1 items-end" style={{ height: 40 }}>
                          {localStatus.cpu_per_core.map((v, i) => (
                            <div
                              key={i}
                              className="flex-1 rounded-sm"
                              style={{
                                height: `${Math.max(v, 2)}%`,
                                backgroundColor: v > 80 ? "var(--err)" : v > 50 ? "#e89b3e" : "var(--accent)",
                                minWidth: 4,
                                maxWidth: 24,
                              }}
                              title={`Core ${i}: ${v.toFixed(1)}%`}
                            />
                          ))}
                        </div>
                      </div>
                    )}

                    {/* CPU frequency + Load average row */}
                    <div className="flex gap-4 text-[12px]">
                      {localStatus.cpu_freq_mhz != null && localStatus.cpu_freq_mhz > 0 && (
                        <div className="text-muted">
                          {t("session:ops.cpuFreq")}:{" "}
                          <span className="text-ink font-medium">{localStatus.cpu_freq_mhz} MHz</span>
                        </div>
                      )}
                      {localStatus.load_avg && (
                        <div className="text-muted">
                          {t("session:ops.loadAvg")}:{" "}
                          <span className="text-ink font-medium">
                            {localStatus.load_avg["1m"]} / {localStatus.load_avg["5m"]} / {localStatus.load_avg["15m"]}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Memory detail */}
                    <div className="flex items-center gap-4">
                      <div className="flex-1 min-w-0"><ProgressBar label={t("session:ops.memory")} value={mem} /></div>
                      <MiniChart data={memHistory} type="line" height={28} width={120} color="var(--accent)" />
                    </div>
                    {localStatus.memory && localStatus.memory.total_gb != null && (
                      <div className="flex gap-4 text-[12px] text-muted -mt-2">
                        <span>{t("session:ops.used")}: <span className="text-ink font-medium">{localStatus.memory.used_gb} GB</span></span>
                        <span>{t("session:ops.available")}: <span className="text-ink font-medium">{localStatus.memory.available_gb} GB</span></span>
                        <span>{t("session:ops.total")}: <span className="text-ink font-medium">{localStatus.memory.total_gb} GB</span></span>
                      </div>
                    )}

                    {/* Swap */}
                    {localStatus.swap && localStatus.swap.total_gb != null && localStatus.swap.total_gb > 0 && (
                      <div>
                        <ProgressBar label={t("session:ops.swap")} value={localStatus.swap.percent ?? 0} />
                        <div className="flex gap-4 text-[12px] text-muted mt-1">
                          <span>{t("session:ops.used")}: <span className="text-ink font-medium">{localStatus.swap.used_gb} GB</span></span>
                          <span>{t("session:ops.total")}: <span className="text-ink font-medium">{localStatus.swap.total_gb} GB</span></span>
                        </div>
                      </div>
                    )}

                    {/* Disk root */}
                    <div className="flex items-center gap-4">
                      <div className="flex-1 min-w-0"><ProgressBar label={t("session:ops.disk")} value={disk} /></div>
                      <MiniChart data={diskHistory} type="line" height={28} width={120} color="var(--accent)" />
                    </div>

                    {/* Disk partitions */}
                    {localStatus.disk_partitions && localStatus.disk_partitions.length > 0 && (
                      <div>
                        <div className="text-[11.5px] text-muted mb-2">{t("session:ops.diskPartitions")}</div>
                        <div className="space-y-2">
                          {localStatus.disk_partitions.map((dp) => (
                            <div key={dp.mountpoint} className="rounded-lg bg-paper border border-line p-2.5">
                              <div className="flex items-center justify-between text-[12px] mb-1">
                                <span className="font-mono text-ink truncate max-w-[200px]" title={dp.device}>{dp.mountpoint}</span>
                                <span className="text-muted text-[11px]">{dp.fstype} &mdash; {dp.used_gb}/{dp.total_gb} GB</span>
                              </div>
                              <div className="w-full h-2 rounded-full bg-line overflow-hidden">
                                <div
                                  className="h-full rounded-full"
                                  style={{
                                    width: `${dp.percent}%`,
                                    backgroundColor: dp.percent > 90 ? "var(--err)" : dp.percent > 70 ? "#e89b3e" : "var(--accent)",
                                  }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {localStatus.uptime_seconds != null && (
                      <div className="text-[12px] text-muted pt-1">
                        {t("session:ops.uptime")}:{" "}
                        <span className="text-ink font-medium">{formatUptime(localStatus.uptime_seconds)}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-[13px] text-muted">{t("session:ops.clickToCheck")}</p>
                )}
              </div>

              {/* Metrics history (Step 7) */}
              <div className={CARD + " p-5 mb-4"}>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.metricsHistory")}</h3>
                  <div className="flex gap-1">
                    {(["1h", "6h", "24h", "7d"] as const).map((r) => (
                      <button
                        key={r}
                        className={
                          "text-[11.5px] px-2 py-1 rounded-md font-medium " +
                          (metricsRange === r ? "bg-accent/10 text-accent" : "text-muted hover:text-ink")
                        }
                        onClick={() => setMetricsRange(r)}
                      >
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
                {metricsHistory.length > 0 ? (
                  <div className="space-y-3">
                    <div>
                      <div className="text-[11.5px] text-muted mb-1">CPU %</div>
                      <MiniChart data={metricsHistory.map((m) => m.cpu)} type="line" height={36} width={600} color="var(--accent)" />
                    </div>
                    <div>
                      <div className="text-[11.5px] text-muted mb-1">{t("session:ops.memory")} %</div>
                      <MiniChart data={metricsHistory.map((m) => m.memory)} type="line" height={36} width={600} color="#e89b3e" />
                    </div>
                    <div>
                      <div className="text-[11.5px] text-muted mb-1">{t("session:ops.disk")} %</div>
                      <MiniChart data={metricsHistory.map((m) => m.disk)} type="line" height={36} width={600} color="#8b5cf6" />
                    </div>
                    <div className="text-[11px] text-faint">
                      {metricsHistory.length} {t("session:ops.dataPoints")}
                    </div>
                  </div>
                ) : (
                  <p className="text-[13px] text-muted">{t("session:ops.noMetrics")}</p>
                )}
              </div>

              {/* Alert Settings (Step 5) */}
              <div className={CARD + " p-5 mb-4"}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.alertSettings")}</h3>
                  <button
                    className="text-[12px] text-accent font-medium"
                    onClick={() => setShowAlertSettings((v) => !v)}
                  >
                    {showAlertSettings ? t("session:ops.hideSettings") : t("session:ops.showSettings")}
                  </button>
                </div>
                {showAlertSettings && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <label className="text-[12.5px] text-muted w-24">CPU %</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        className="w-20 text-[13px] px-2 py-1 rounded-lg border border-line bg-paper text-ink"
                        value={alertThresholds.cpu}
                        onChange={(e) => setAlertThresholds((p) => ({ ...p, cpu: Number(e.target.value) || 90 }))}
                      />
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="text-[12.5px] text-muted w-24">{t("session:ops.memory")} %</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        className="w-20 text-[13px] px-2 py-1 rounded-lg border border-line bg-paper text-ink"
                        value={alertThresholds.memory}
                        onChange={(e) => setAlertThresholds((p) => ({ ...p, memory: Number(e.target.value) || 85 }))}
                      />
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="text-[12.5px] text-muted w-24">{t("session:ops.disk")} %</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        className="w-20 text-[13px] px-2 py-1 rounded-lg border border-line bg-paper text-ink"
                        value={alertThresholds.disk}
                        onChange={(e) => setAlertThresholds((p) => ({ ...p, disk: Number(e.target.value) || 90 }))}
                      />
                    </div>
                    <button
                      className="text-[12.5px] px-3 py-1.5 rounded-lg bg-accent text-white font-medium"
                      onClick={saveAlertConfig}
                      disabled={savingThresholds}
                    >
                      {savingThresholds ? t("common:status.loading") : t("common:button.save")}
                    </button>
                  </div>
                )}
              </div>

              {/* Docker containers */}
              {containers && containers.length > 0 && (
                <div className={CARD + " p-5 mb-4"}>
                  <h3 className="text-[14px] font-semibold text-ink mb-3">{t("session:ops.dockerContainers")}</h3>
                  <div className="space-y-2">
                    {containers.map((c, i) => (
                      <div key={i} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line">
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-medium text-ink truncate">{c.name}</div>
                          <div className="text-[11.5px] text-faint truncate">{c.image}</div>
                        </div>
                        <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " +
                          (c.status.toLowerCase().includes("up") ? "bg-ok/10 text-ok" : "bg-faint/10 text-faint")}>
                          {c.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent logs */}
              {localStatus?.logs && localStatus.logs.length > 0 && (
                <div className={CARD + " p-5"}>
                  <h3 className="text-[14px] font-semibold text-ink mb-3">{t("session:ops.recentLogs")}</h3>
                  <div className="bg-paper rounded-lg border border-line p-3 font-mono text-[12px] text-muted space-y-1 max-h-48 overflow-y-auto">
                    {localStatus.logs.map((log, i) => (<div key={i}>{log}</div>))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* PROCESSES TAB */}
          {activeTab === "processes" && (
            <div className={CARD + " p-5 mb-4"}>
              <div className="flex items-center gap-3 mb-4">
                <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.processes")}</h3>
                <input
                  type="text"
                  className="flex-1 text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
                  placeholder={t("session:ops.filterProcesses")}
                  value={processFilter}
                  onChange={(e) => setProcessFilter(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && fetchProcesses()}
                />
                <button className="text-[12.5px] text-accent font-medium" onClick={fetchProcesses}>
                  <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                </button>
              </div>
              {processes.length === 0 ? (
                <p className="text-[13px] text-muted">{t("session:ops.noProcesses")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[12.5px]">
                    <thead>
                      <tr className="text-muted text-left border-b border-line">
                        <th className="pb-2 pr-4 cursor-pointer select-none" onClick={() => toggleProcSort("pid")}>
                          PID {procSortKey === "pid" ? (procSortAsc ? "▲" : "▼") : ""}
                        </th>
                        <th className="pb-2 pr-4 cursor-pointer select-none" onClick={() => toggleProcSort("name")}>
                          Name {procSortKey === "name" ? (procSortAsc ? "▲" : "▼") : ""}
                        </th>
                        <th className="pb-2 pr-4">{t("session:ops.username")}</th>
                        <th className="pb-2 pr-4 cursor-pointer select-none" onClick={() => toggleProcSort("cpu_percent")}>
                          CPU% {procSortKey === "cpu_percent" ? (procSortAsc ? "▲" : "▼") : ""}
                        </th>
                        <th className="pb-2 pr-4 cursor-pointer select-none" onClick={() => toggleProcSort("memory_percent")}>
                          MEM% {procSortKey === "memory_percent" ? (procSortAsc ? "▲" : "▼") : ""}
                        </th>
                        <th className="pb-2 pr-4">{t("session:ops.threads")}</th>
                        <th className="pb-2 pr-4">Status</th>
                        <th className="pb-2 pr-4">{t("session:ops.command")}</th>
                        <th className="pb-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedProcesses.map((p) => {
                        const cpuVal = p.cpu_percent ?? 0;
                        const cpuColor = cpuVal > 50 ? "text-err font-semibold" : cpuVal > 20 ? "text-[#e89b3e] font-medium" : "";
                        return (
                          <tr key={p.pid} className="border-b border-line/50 text-ink">
                            <td className="py-1.5 pr-4 font-mono">{p.pid}</td>
                            <td className="py-1.5 pr-4 truncate max-w-[160px]">{p.name}</td>
                            <td className="py-1.5 pr-4 text-muted truncate max-w-[80px]">{p.username ?? "-"}</td>
                            <td className={"py-1.5 pr-4 " + cpuColor}>{cpuVal.toFixed(1)}</td>
                            <td className="py-1.5 pr-4">{p.memory_percent?.toFixed(1) ?? "-"}</td>
                            <td className="py-1.5 pr-4 text-muted">{p.num_threads ?? "-"}</td>
                            <td className="py-1.5 pr-4">{p.status ?? "-"}</td>
                            <td className="py-1.5 pr-4 text-muted truncate max-w-[180px] font-mono text-[11px]" title={p.cmdline || ""}>
                              {p.cmdline ? p.cmdline.slice(0, 60) : "-"}
                            </td>
                            <td className="py-1.5">
                              <button
                                className="text-[11px] px-2 py-0.5 rounded bg-err/10 text-err font-medium"
                                onClick={() => setKillTarget(p)}
                              >
                                {t("session:ops.killProcess")}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* PORTS TAB */}
          {activeTab === "ports" && (
            <div className={CARD + " p-5 mb-4"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.ports")}</h3>
                <button className="text-[12.5px] text-accent font-medium" onClick={fetchPorts}>
                  <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                </button>
              </div>
              {ports.length === 0 ? (
                <p className="text-[13px] text-muted">{t("session:ops.noPorts")}</p>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  {ports.map((p) => (
                    <div key={p.port} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-paper border border-line">
                      <span className={"w-2 h-2 rounded-full " + (p.status === "open" ? "bg-ok" : "bg-faint")} />
                      <span className="text-[13px] font-mono text-ink">{p.port}</span>
                      <span className={"text-[11px] ml-auto " + (p.status === "open" ? "text-ok" : "text-faint")}>{p.status}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* DOCKER TAB (Step 6) */}
          {activeTab === "docker" && (
            <div className={CARD + " p-5 mb-4"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.docker")}</h3>
                <button className="text-[12.5px] text-accent font-medium" onClick={fetchDockerContainers}>
                  <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                </button>
              </div>
              {dockerLoading ? (
                <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
              ) : dockerContainers.length === 0 ? (
                <p className="text-[13px] text-muted">{t("session:ops.noDockerContainers")}</p>
              ) : (
                <div className="space-y-2">
                  {dockerContainers.map((c) => {
                    const cId = c.ID || c.Names || "";
                    const isRunning = (c.State || c.Status || "").toLowerCase().includes("running") ||
                                      (c.Status || "").toLowerCase().startsWith("up");
                    return (
                      <div key={cId} className="px-3 py-2.5 rounded-lg bg-paper border border-line">
                        <div className="flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] font-medium text-ink truncate">{c.Names || cId}</div>
                            <div className="text-[11.5px] text-faint truncate">{c.Image} {c.Ports ? `- ${c.Ports}` : ""}</div>
                          </div>
                          <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " +
                            (isRunning ? "bg-ok/10 text-ok" : "bg-faint/10 text-faint")}>
                            {c.Status || c.State || "unknown"}
                          </span>
                          <div className="flex gap-1">
                            {!isRunning && (
                              <button
                                className="text-[11px] px-2 py-0.5 rounded bg-ok/10 text-ok font-medium"
                                onClick={() => dockerAction(cId, "start")}
                                disabled={dockerActionLoading === cId}
                              >
                                {t("session:ops.dockerStart")}
                              </button>
                            )}
                            {isRunning && (
                              <button
                                className="text-[11px] px-2 py-0.5 rounded bg-err/10 text-err font-medium"
                                onClick={() => dockerAction(cId, "stop")}
                                disabled={dockerActionLoading === cId}
                              >
                                {t("session:ops.dockerStop")}
                              </button>
                            )}
                            <button
                              className="text-[11px] px-2 py-0.5 rounded bg-accent/10 text-accent font-medium"
                              onClick={() => dockerAction(cId, "restart")}
                              disabled={dockerActionLoading === cId}
                            >
                              {t("session:ops.dockerRestart")}
                            </button>
                            <button
                              className="text-[11px] px-2 py-0.5 rounded border border-line text-muted font-medium"
                              onClick={() => fetchDockerLogs(cId)}
                            >
                              {t("session:ops.dockerLogs")}
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Docker logs viewer */}
              {dockerLogs && (
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-[13px] font-semibold text-ink">
                      {t("session:ops.dockerLogs")} — {dockerLogs.id}
                    </h4>
                    <button
                      className="text-[11px] text-muted hover:text-ink"
                      onClick={() => setDockerLogs(null)}
                    >
                      {t("common:button.close")}
                    </button>
                  </div>
                  <div className="bg-paper rounded-lg border border-line p-3 font-mono text-[11.5px] text-muted max-h-64 overflow-y-auto whitespace-pre-wrap">
                    {dockerLogs.logs}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* NETWORK TAB (S11) */}
          {activeTab === "network" && (
            <div className={CARD + " p-5 mb-4"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.network")}</h3>
                <button className="text-[12.5px] text-accent font-medium" onClick={fetchNetworkStats}>
                  <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                </button>
              </div>
              {networkLoading ? (
                <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
              ) : !networkStats || !networkStats.ok ? (
                <p className="text-[13px] text-muted">{networkStats?.error || t("session:ops.noNetworkData")}</p>
              ) : (
                <>
                  {/* Total throughput summary */}
                  <div className="flex gap-4 mb-4 text-[12.5px]">
                    {networkStats.total && (
                      <>
                        <div className="flex-1 rounded-lg bg-paper border border-line p-3 text-center">
                          <div className="text-faint mb-1">Total Sent</div>
                          <div className="text-ink font-semibold text-[14px]">{formatBytes(networkStats.total.bytes_sent)}</div>
                        </div>
                        <div className="flex-1 rounded-lg bg-paper border border-line p-3 text-center">
                          <div className="text-faint mb-1">Total Received</div>
                          <div className="text-ink font-semibold text-[14px]">{formatBytes(networkStats.total.bytes_recv)}</div>
                        </div>
                        <div className="flex-1 rounded-lg bg-paper border border-line p-3 text-center">
                          <div className="text-faint mb-1">{t("session:ops.activeConnections")}</div>
                          <div className="text-ink font-semibold text-[14px]">{networkStats.connections === -1 ? "N/A" : networkStats.connections}</div>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Interface cards */}
                  <div className="space-y-3">
                    {Object.entries(networkStats.interfaces || {}).map(([iface, s]) => (
                      <div key={iface} className="rounded-lg bg-paper border border-line p-3">
                        <div className="flex items-center gap-2 mb-2">
                          <span className={"w-2 h-2 rounded-full " + (s.is_up !== false ? "bg-ok" : "bg-faint")} />
                          <span className="text-[13px] font-semibold text-ink font-mono">{iface}</span>
                          {s.speed_mbps != null && s.speed_mbps > 0 && (
                            <span className="text-[11px] text-faint">{s.speed_mbps} Mbps</span>
                          )}
                          {s.mtu != null && (
                            <span className="text-[11px] text-faint">MTU {s.mtu}</span>
                          )}
                          {s.addresses?.map((a, i) => (
                            <span key={i} className="text-[11px] px-1.5 py-0.5 rounded bg-accent/10 text-accent font-mono">
                              {a.address}
                            </span>
                          ))}
                        </div>
                        <div className="grid grid-cols-4 gap-3 text-[11.5px]">
                          <div>
                            <div className="text-faint">Sent</div>
                            <div className="text-ink font-medium">{formatBytes(s.bytes_sent)}</div>
                          </div>
                          <div>
                            <div className="text-faint">Received</div>
                            <div className="text-ink font-medium">{formatBytes(s.bytes_recv)}</div>
                          </div>
                          <div>
                            <div className="text-faint">Packets ↑/↓</div>
                            <div className="text-ink font-medium">{s.packets_sent.toLocaleString()} / {s.packets_recv.toLocaleString()}</div>
                          </div>
                          <div>
                            <div className="text-faint">Errors / Drops</div>
                            <div className={"font-medium " + ((s.errin + s.errout + (s.dropin || 0) + (s.dropout || 0)) > 0 ? "text-err" : "text-ink")}>
                              {s.errin + s.errout} / {(s.dropin || 0) + (s.dropout || 0)}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* HEALTH CHECKS TAB (S12) */}
          {activeTab === "health" && (
            <div className={CARD + " p-5 mb-4"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.healthChecks")}</h3>
                <div className="flex gap-2">
                  <button
                    className="text-[12.5px] text-accent font-medium"
                    onClick={runHealthChecks}
                    disabled={healthRunning}
                  >
                    {healthRunning ? t("common:status.loading") : t("session:ops.runChecks")}
                  </button>
                  <button className="text-[12.5px] text-accent font-medium" onClick={fetchHealthChecks}>
                    <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                  </button>
                </div>
              </div>
              {healthChecks.length === 0 ? (
                <p className="text-[13px] text-muted mb-4">{t("session:ops.noHealthChecks")}</p>
              ) : (
                <div className="space-y-2 mb-4">
                  {healthChecks.map((c, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-paper border border-line">
                      <span className={"w-2 h-2 rounded-full " +
                        (c.last_status === "ok" ? "bg-ok" : c.last_status === "fail" ? "bg-err" : "bg-faint")} />
                      <span className="text-[13px] font-medium text-ink">{c.type}</span>
                      <span className="text-[12px] text-muted font-mono truncate flex-1">{c.target}</span>
                      <span className={"text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (c.last_status === "ok" ? "bg-ok/10 text-ok" :
                         c.last_status === "fail" ? "bg-err/10 text-err" : "bg-faint/10 text-faint")}>
                        {c.last_status}
                      </span>
                      {c.last_check > 0 && (
                        <span className="text-[11px] text-faint">
                          {new Date(c.last_check * 1000).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div className="border-t border-line pt-4">
                <h4 className="text-[13px] font-semibold text-ink mb-3">{t("session:ops.addCheck")}</h4>
                <div className="flex gap-2 items-end">
                  <div>
                    <label className="block text-[11px] text-muted mb-1">{t("session:ops.checkType")}</label>
                    <select
                      className="text-[13px] px-2 py-1.5 rounded-lg border border-line bg-paper text-ink"
                      value={newCheckType}
                      onChange={(e) => setNewCheckType(e.target.value)}
                    >
                      <option value="port">Port</option>
                      <option value="http">HTTP</option>
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className="block text-[11px] text-muted mb-1">{t("session:ops.checkTarget")}</label>
                    <input
                      type="text"
                      className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
                      placeholder={newCheckType === "port" ? "80,443" : "http://localhost:8080"}
                      value={newCheckTarget}
                      onChange={(e) => setNewCheckTarget(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && addHealthCheck()}
                    />
                  </div>
                  <button
                    className="text-[12.5px] px-3 py-1.5 rounded-lg bg-accent text-white font-medium"
                    onClick={addHealthCheck}
                  >
                    {t("session:ops.addCheck")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* SSH servers */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">{t("session:ops.sshServers")}</h3>
              <div className="flex gap-2">
                <button
                  className="text-[12.5px] text-accent font-medium"
                  onClick={() => setSshModal({ open: true, server: null })}
                >
                  + {t("session:ops.addServer")}
                </button>
                <button className="text-[12.5px] text-accent font-medium" onClick={fetchServers}>
                  <Icon name="refresh" size={13} className="inline mr-1" />{t("common:button.refresh")}
                </button>
              </div>
            </div>
            {loading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : servers.length === 0 ? (
              <p className="text-[13px] text-muted">{t("session:ops.noServers")}</p>
            ) : (
              <div className="space-y-2">
                {servers.map((s) => (
                  <div
                    key={serverId(s)}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <Icon name="wrench" size={15} className="text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {s.label || s.name || s.host}
                      </div>
                      <div className="text-[11.5px] text-faint truncate">
                        {s.username || s.user ? `${s.username || s.user}@` : ""}{s.host}:{s.port ?? 22}
                      </div>
                    </div>
                    <button
                      className="text-[11.5px] text-accent hover:underline"
                      onClick={() => setSshModal({ open: true, server: s })}
                    >
                      Edit
                    </button>
                    <button
                      className="text-[11.5px] text-err hover:underline"
                      onClick={() => setDeleteTarget(s)}
                    >
                      Delete
                    </button>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (s.status === "connected" ? "bg-ok/10 text-ok" : "bg-faint/10 text-faint")
                      }
                    >
                      {s.status || "unknown"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Modals */}
      {sshModal.open && (
        <SshModal
          server={sshModal.server}
          onClose={() => setSshModal({ open: false, server: null })}
          onSaved={fetchServers}
        />
      )}
      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.label || deleteTarget.name || deleteTarget.host}
          onConfirm={() => handleDeleteServer(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
      {killTarget && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={() => setKillTarget(null)}>
          <div className="bg-panel rounded-xl2 border border-line p-5 w-[340px]" onClick={(e) => e.stopPropagation()}>
            <p className="text-[14px] text-ink mb-2">{t("session:ops.killConfirm")}</p>
            <p className="text-[12.5px] text-muted mb-4">
              PID: <span className="font-mono">{killTarget.pid}</span> — {killTarget.name}
            </p>
            <div className="flex justify-end gap-2">
              <button className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted" onClick={() => setKillTarget(null)}>
                {t("common:button.cancel")}
              </button>
              <button
                className="text-[13px] px-3 py-1.5 rounded-lg bg-err text-white font-medium"
                onClick={() => killProcess(killTarget.pid)}
                disabled={killing}
              >
                {killing ? t("common:status.loading") : t("session:ops.killProcess")}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
