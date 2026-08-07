import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";
import { MiniChart } from "./MiniChart";
import { ProgressBar } from "./ProgressBar";

const CARD = "rounded-xl2 border border-line bg-panel";

const POLL_INTERVAL_MS = 10_000;
const MAX_HISTORY = 30;

interface SshServer {
  id: string;
  name: string;
  host: string;
  port?: number;
  user?: string;
  status?: string;
}

interface ServerStatus {
  cpu_percent?: number;
  memory?: { percent?: number };
  disk_root?: { percent?: number };
  uptime_seconds?: number;
  docker_containers?: { name: string; status: string; image: string }[];
  /* fallback fields from the existing simulated format */
  cpu?: number;
  disk?: number;
  logs?: string[];
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

export function OpsView() {
  const { t } = useTranslation(["session", "common"]);
  const [servers, setServers] = useState<SshServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [localStatus, setLocalStatus] = useState<ServerStatus | null>(null);
  const [polling, setPolling] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Metric history (last MAX_HISTORY samples)
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [memHistory, setMemHistory] = useState<number[]>([]);
  const [diskHistory, setDiskHistory] = useState<number[]>([]);

  const fetchServers = useCallback(() => {
    setLoading(true);
    fetch("/v1/ssh/servers")
      .then((r) => (r.ok ? r.json() : { servers: [] }))
      .then((data) => {
        const list = Array.isArray(data) ? data : Array.isArray(data?.servers) ? data.servers : [];
        setServers(list);
      })
      .catch(() => setServers([]))
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
      })
      .catch(() => {
        /* endpoint may not exist yet — ignore silently */
      });
  }, []);

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

  // Initial fetch + polling
  useEffect(() => {
    fetchStatus();

    if (polling) {
      timerRef.current = setInterval(fetchStatus, POLL_INTERVAL_MS);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchStatus, polling]);

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

          {/* Local server status with sparklines */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:ops.localStatus")}
              </h3>
              <button
                className={
                  "text-[12px] px-2.5 py-1.5 rounded-lg border border-line " +
                  (polling
                    ? "text-ok bg-ok/5"
                    : "text-muted bg-paper")
                }
                onClick={() => setPolling((p) => !p)}
              >
                {t("session:ops.autoRefresh", { seconds: POLL_INTERVAL_MS / 1000 })}
              </button>
            </div>

            {localStatus ? (
              <div className="space-y-4">
                {/* CPU */}
                <div className="flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <ProgressBar label="CPU" value={cpu} />
                  </div>
                  <MiniChart
                    data={cpuHistory}
                    type="line"
                    height={28}
                    width={120}
                    color="var(--accent)"
                  />
                </div>

                {/* Memory */}
                <div className="flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <ProgressBar
                      label={t("session:ops.memory")}
                      value={mem}
                    />
                  </div>
                  <MiniChart
                    data={memHistory}
                    type="line"
                    height={28}
                    width={120}
                    color="var(--accent)"
                  />
                </div>

                {/* Disk */}
                <div className="flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <ProgressBar
                      label={t("session:ops.disk")}
                      value={disk}
                    />
                  </div>
                  <MiniChart
                    data={diskHistory}
                    type="line"
                    height={28}
                    width={120}
                    color="var(--accent)"
                  />
                </div>

                {/* Uptime */}
                {localStatus.uptime_seconds != null && (
                  <div className="text-[12px] text-muted pt-1">
                    {t("session:ops.uptime")}:{" "}
                    <span className="text-ink font-medium">
                      {formatUptime(localStatus.uptime_seconds)}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-muted">
                {t("session:ops.clickToCheck")}
              </p>
            )}
          </div>

          {/* SSH servers */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:ops.sshServers")}
              </h3>
              <button
                className="text-[12.5px] text-accent font-medium"
                onClick={fetchServers}
              >
                <Icon name="refresh" size={13} className="inline mr-1" />
                {t("common:button.refresh")}
              </button>
            </div>
            {loading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : servers.length === 0 ? (
              <p className="text-[13px] text-muted">{t("session:ops.noServers")}</p>
            ) : (
              <div className="space-y-2">
                {servers.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <Icon name="wrench" size={15} className="text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {s.name || s.host}
                      </div>
                      <div className="text-[11.5px] text-faint truncate">
                        {s.user ? `${s.user}@` : ""}{s.host}:{s.port ?? 22}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (s.status === "connected"
                          ? "bg-ok/10 text-ok"
                          : "bg-faint/10 text-faint")
                      }
                    >
                      {s.status || "unknown"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Docker containers */}
          {containers && containers.length > 0 && (
            <div className={CARD + " p-5 mb-4"}>
              <h3 className="text-[14px] font-semibold text-ink mb-3">
                {t("session:ops.dockerContainers")}
              </h3>
              <div className="space-y-2">
                {containers.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {c.name}
                      </div>
                      <div className="text-[11.5px] text-faint truncate">
                        {c.image}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (c.status.toLowerCase().includes("up")
                          ? "bg-ok/10 text-ok"
                          : "bg-faint/10 text-faint")
                      }
                    >
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
              <h3 className="text-[14px] font-semibold text-ink mb-3">
                {t("session:ops.recentLogs")}
              </h3>
              <div className="bg-paper rounded-lg border border-line p-3 font-mono text-[12px] text-muted space-y-1 max-h-48 overflow-y-auto">
                {localStatus.logs.map((log, i) => (
                  <div key={i}>{log}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
