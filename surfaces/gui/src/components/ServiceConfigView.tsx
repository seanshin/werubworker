import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

type Tab = "ssh" | "database" | "cloud";

interface SshServer {
  id: string;
  name: string;
  host: string;
  port?: number;
  user?: string;
}

interface DatabaseConfig {
  id: string;
  name: string;
  type: string;
  host: string;
  port?: number;
  database?: string;
}

interface CloudProvider {
  id: string;
  provider: string;
  label: string;
  configured: boolean;
}

export function ServiceConfigView() {
  const { t } = useTranslation(["session", "common"]);
  const [tab, setTab] = useState<Tab>("ssh");
  const [sshServers, setSshServers] = useState<SshServer[]>([]);
  const [databases, setDatabases] = useState<DatabaseConfig[]>([]);
  const [cloudProviders] = useState<CloudProvider[]>([
    { id: "aws", provider: "AWS", label: "Amazon Web Services", configured: false },
    { id: "cf", provider: "Cloudflare", label: "Cloudflare", configured: false },
    { id: "wasabi", provider: "Wasabi", label: "Wasabi Storage", configured: false },
  ]);
  const [loading, setLoading] = useState(true);
  const [showMasked, setShowMasked] = useState<Set<string>>(new Set());

  const toggleMask = (id: string) =>
    setShowMasked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const fetchSsh = useCallback(() => {
    setLoading(true);
    fetch("/v1/ssh/servers")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setSshServers(Array.isArray(data) ? data : []))
      .catch(() => setSshServers([]))
      .finally(() => setLoading(false));
  }, []);

  const fetchDatabases = useCallback(() => {
    setLoading(true);
    fetch("/v1/databases")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setDatabases(Array.isArray(data) ? data : []))
      .catch(() => setDatabases([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (tab === "ssh") fetchSsh();
    else if (tab === "database") fetchDatabases();
    else setLoading(false);
  }, [tab, fetchSsh, fetchDatabases]);

  const tabs: { key: Tab; labelKey: string }[] = [
    { key: "ssh", labelKey: "session:serviceConfig.sshTab" },
    { key: "database", labelKey: "session:serviceConfig.databaseTab" },
    { key: "cloud", labelKey: "session:serviceConfig.cloudTab" },
  ];

  const serviceRow = (
    id: string,
    title: string,
    subtitle: string,
    status?: string,
  ) => (
    <div
      key={id}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
    >
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-medium text-ink truncate">{title}</div>
        <div className="text-[11.5px] text-faint truncate">
          {showMasked.has(id) ? subtitle : subtitle.replace(/./g, "\u2022")}
        </div>
      </div>
      <button
        className="text-[11px] text-muted hover:text-ink"
        onClick={() => toggleMask(id)}
        title={showMasked.has(id) ? "Hide" : "Show"}
      >
        <Icon name={showMasked.has(id) ? "shield" : "shield"} size={14} />
      </button>
      {status && (
        <span
          className={
            "text-[11px] px-2 py-0.5 rounded-full font-medium " +
            (status === "connected"
              ? "bg-ok/10 text-ok"
              : "bg-faint/10 text-faint")
          }
        >
          {status}
        </span>
      )}
      <button className="text-[11px] text-accent font-medium">
        {t("common:button.edit")}
      </button>
      <button className="text-[11px] text-danger font-medium">
        {t("common:button.remove")}
      </button>
    </div>
  );

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:serviceConfig.title")}
            sub={t("session:serviceConfig.sub")}
          />

          {/* Tab bar */}
          <div className="flex gap-1 mb-5 border-b border-line">
            {tabs.map((tb) => (
              <button
                key={tb.key}
                className={
                  "px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors " +
                  (tab === tb.key
                    ? "border-accent text-ink"
                    : "border-transparent text-muted hover:text-ink")
                }
                onClick={() => setTab(tb.key)}
              >
                {t(tb.labelKey)}
              </button>
            ))}
          </div>

          {loading ? (
            <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
          ) : tab === "ssh" ? (
            <div className={CARD + " p-5"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">
                  {t("session:serviceConfig.sshTab")}
                </h3>
                <button className={BTN_ACCENT}>
                  + {t("common:button.add")}
                </button>
              </div>
              {sshServers.length === 0 ? (
                <p className="text-[13px] text-muted">
                  {t("session:serviceConfig.noItems")}
                </p>
              ) : (
                <div className="space-y-2">
                  {sshServers.map((s) =>
                    serviceRow(
                      s.id,
                      s.name || s.host,
                      `${s.user || "root"}@${s.host}:${s.port ?? 22}`,
                    ),
                  )}
                </div>
              )}
            </div>
          ) : tab === "database" ? (
            <div className={CARD + " p-5"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">
                  {t("session:serviceConfig.databaseTab")}
                </h3>
                <button className={BTN_ACCENT}>
                  + {t("common:button.add")}
                </button>
              </div>
              {databases.length === 0 ? (
                <p className="text-[13px] text-muted">
                  {t("session:serviceConfig.noItems")}
                </p>
              ) : (
                <div className="space-y-2">
                  {databases.map((d) =>
                    serviceRow(
                      d.id,
                      d.name || d.database || d.host,
                      `${d.type}://${d.host}:${d.port ?? ""}/${d.database ?? ""}`,
                    ),
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className={CARD + " p-5"}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[14px] font-semibold text-ink">
                  {t("session:serviceConfig.cloudTab")}
                </h3>
              </div>
              <div className="space-y-2">
                {cloudProviders.map((cp) => (
                  <div
                    key={cp.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink">
                        {cp.label}
                      </div>
                      <div className="text-[11.5px] text-faint">
                        {cp.provider}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (cp.configured
                          ? "bg-ok/10 text-ok"
                          : "bg-faint/10 text-faint")
                      }
                    >
                      {cp.configured
                        ? t("common:status.connected")
                        : t("common:status.notSetUp")}
                    </span>
                    <button className={BTN_BORDERED}>
                      {cp.configured
                        ? t("common:button.edit")
                        : t("common:button.connect")}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
