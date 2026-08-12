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

// ---------------------------------------------------------------------------
// Rotation badge & Audit log helpers
// ---------------------------------------------------------------------------
interface ExpiringCredential {
  key: string;
  expires: string;
  expired: boolean;
}

interface AuditEntry {
  timestamp: string;
  action: string;
  key: string;
}

function RotationBadge({ expiring }: { expiring: ExpiringCredential[] }) {
  const { t } = useTranslation(["session"]);
  if (expiring.length === 0) return null;
  return (
    <div className="mb-4 space-y-1">
      {expiring.map((c) => (
        <div
          key={c.key}
          className={
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] font-medium " +
            (c.expired
              ? "bg-danger/10 text-danger"
              : "bg-warn/10 text-warn")
          }
        >
          <Icon name="shield" size={13} />
          <span>
            {c.key} — {c.expired ? t("session:wiki.expired") : t("session:wiki.rotationDue")} ({c.expires})
          </span>
        </div>
      ))}
    </div>
  );
}

function AuditLogSection() {
  const { t } = useTranslation(["session"]);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(7);

  const fetchAudit = useCallback(() => {
    setLoading(true);
    fetch(`/v1/vault/audit?days=${days}`)
      .then((r) => r.json())
      .then((d) => setEntries(d.entries || []))
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(() => { fetchAudit(); }, [fetchAudit]);

  return (
    <div className={CARD + " p-5 mt-6"}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[14px] font-semibold text-ink">
          {t("session:serviceConfig.auditLog")}
        </h3>
        <select
          className="text-[12px] px-2 py-1 rounded-lg border border-line bg-paper text-ink"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={1}>1 {t("session:serviceConfig.days")}</option>
          <option value={7}>7 {t("session:serviceConfig.days")}</option>
          <option value={30}>30 {t("session:serviceConfig.days")}</option>
        </select>
      </div>
      {loading ? (
        <p className="text-[12px] text-muted">{t("common:status.loading")}</p>
      ) : entries.length === 0 ? (
        <p className="text-[12px] text-muted">{t("session:serviceConfig.noAuditEntries")}</p>
      ) : (
        <div className="max-h-[240px] overflow-y-auto hairline-scroll">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-muted text-left border-b border-line">
                <th className="pb-1.5 pr-3">{t("session:serviceConfig.auditTime")}</th>
                <th className="pb-1.5 pr-3">{t("session:serviceConfig.auditAction")}</th>
                <th className="pb-1.5">{t("session:serviceConfig.auditKey")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.slice(0, 100).map((e, i) => (
                <tr key={i} className="border-b border-line/30 text-ink">
                  <td className="py-1 pr-3 text-faint font-mono whitespace-nowrap">
                    {e.timestamp.replace("T", " ").slice(0, 19)}
                  </td>
                  <td className="py-1 pr-3">{e.action}</td>
                  <td className="py-1 font-mono">{e.key}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

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
  name: string;
  provider: string;
  configured: boolean;
  region?: string;
  testing?: boolean;
  testResult?: string;
}

// ---------------------------------------------------------------------------
// Field component (reused from OpsView pattern)
// ---------------------------------------------------------------------------
function Field({
  label,
  value,
  onChange,
  placeholder,
  type,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
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

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="block text-[12px] text-muted mb-1">{label}</label>
      <select
        className="w-full text-[13px] px-3 py-1.5 rounded-lg border border-line bg-paper text-ink"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SSH Modal
// ---------------------------------------------------------------------------
function SshModal({
  server,
  onClose,
  onSaved,
}: {
  server: SshServer | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation(["session", "common"]);
  const isEdit = server !== null;
  const [host, setHost] = useState(server?.host ?? "");
  const [port, setPort] = useState(server?.port ?? 22);
  const [username, setUsername] = useState(server?.user ?? "");
  const [keyPath, setKeyPath] = useState("");
  const [label, setLabel] = useState(server?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    if (!host.trim()) {
      setError("Host is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = {
        host: host.trim(),
        port,
        username: username.trim(),
        key_path: keyPath.trim(),
        label: label.trim(),
      };
      const url = isEdit
        ? `/v1/ssh/servers/${encodeURIComponent(server!.id)}`
        : "/v1/ssh/servers";
      const method = isEdit ? "PUT" : "POST";
      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        onSaved();
        onClose();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.error || "Save failed");
      }
    } catch {
      setError("Network error");
    }
    setSaving(false);
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-panel rounded-xl2 border border-line p-6 w-[420px] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold text-ink mb-4">
          {isEdit ? t("common:button.edit") : t("common:button.add")} SSH Server
        </h3>
        <div className="space-y-3">
          <Field
            label="Host"
            value={host}
            onChange={setHost}
            placeholder="192.168.1.10"
          />
          <div className="flex gap-3">
            <div className="flex-1">
              <Field
                label="Port"
                value={String(port)}
                onChange={(v) => setPort(Number(v) || 22)}
                type="number"
              />
            </div>
            <div className="flex-1">
              <Field
                label="Username"
                value={username}
                onChange={setUsername}
                placeholder="deploy"
              />
            </div>
          </div>
          <Field
            label="Key Path"
            value={keyPath}
            onChange={setKeyPath}
            placeholder="~/.ssh/id_ed25519"
          />
          <Field
            label="Label"
            value={label}
            onChange={setLabel}
            placeholder="Production Web"
          />
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button
            className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted"
            onClick={onClose}
          >
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
  );
}

// ---------------------------------------------------------------------------
// Database Modal
// ---------------------------------------------------------------------------
interface DbFormData {
  name: string;
  type: string;
  host: string;
  port: string;
  database: string;
  user: string;
  password: string;
  path: string;
}

function DatabaseModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation(["session", "common"]);
  const [form, setForm] = useState<DbFormData>({
    name: "",
    type: "postgresql",
    host: "",
    port: "",
    database: "",
    user: "",
    password: "",
    path: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (key: keyof DbFormData, val: string) =>
    setForm((prev) => ({ ...prev, [key]: val }));

  const isSqlite = form.type === "sqlite";

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError("Name is required");
      return;
    }
    if (!isSqlite && !form.host.trim()) {
      setError("Host is required");
      return;
    }
    if (isSqlite && !form.path.trim()) {
      setError("Path is required for SQLite");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        type: form.type,
      };
      if (isSqlite) {
        body.path = form.path.trim();
      } else {
        body.host = form.host.trim();
        if (form.port) body.port = Number(form.port);
        if (form.database) body.database = form.database.trim();
        if (form.user) body.user = form.user.trim();
        if (form.password) body.password = form.password;
      }
      const r = await fetch("/v1/databases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        onSaved();
        onClose();
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.error || "Save failed");
      }
    } catch {
      setError("Network error");
    }
    setSaving(false);
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-panel rounded-xl2 border border-line p-6 w-[420px] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold text-ink mb-4">
          {t("common:button.add")} Database
        </h3>
        <div className="space-y-3">
          <Field
            label="Name"
            value={form.name}
            onChange={(v) => set("name", v)}
            placeholder="my-database"
          />
          <SelectField
            label="Type"
            value={form.type}
            onChange={(v) => set("type", v)}
            options={[
              { value: "postgresql", label: "PostgreSQL" },
              { value: "mysql", label: "MySQL" },
              { value: "sqlite", label: "SQLite" },
            ]}
          />
          {isSqlite ? (
            <Field
              label="Path"
              value={form.path}
              onChange={(v) => set("path", v)}
              placeholder="/path/to/database.db"
            />
          ) : (
            <>
              <div className="flex gap-3">
                <div className="flex-[2]">
                  <Field
                    label="Host"
                    value={form.host}
                    onChange={(v) => set("host", v)}
                    placeholder="localhost"
                  />
                </div>
                <div className="flex-1">
                  <Field
                    label="Port"
                    value={form.port}
                    onChange={(v) => set("port", v)}
                    placeholder={form.type === "mysql" ? "3306" : "5432"}
                    type="number"
                  />
                </div>
              </div>
              <Field
                label="Database"
                value={form.database}
                onChange={(v) => set("database", v)}
                placeholder="mydb"
              />
              <div className="flex gap-3">
                <div className="flex-1">
                  <Field
                    label="User"
                    value={form.user}
                    onChange={(v) => set("user", v)}
                    placeholder="postgres"
                  />
                </div>
                <div className="flex-1">
                  <Field
                    label="Password"
                    value={form.password}
                    onChange={(v) => set("password", v)}
                    type="password"
                  />
                </div>
              </div>
            </>
          )}
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button
            className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted"
            onClick={onClose}
          >
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
  );
}

// ---------------------------------------------------------------------------
// Cloud Provider Modal
// ---------------------------------------------------------------------------
function CloudModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation(["session", "common"]);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("aws");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [region, setRegion] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    if (!name.trim()) {
      setError(t("session:serviceConfig.nameRequired"));
      return;
    }
    if (!apiKey.trim()) {
      setError(t("session:serviceConfig.apiKeyRequired"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const r = await fetch("/v1/cloud/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          provider: provider.trim(),
          api_key: apiKey.trim(),
          api_secret: apiSecret.trim(),
          region: region.trim(),
        }),
      });
      if (r.ok) {
        const data = await r.json();
        if (data.ok) {
          onSaved();
          onClose();
        } else {
          setError(data.error || "Save failed");
        }
      } else {
        const d = await r.json().catch(() => ({}));
        setError(d.error || "Save failed");
      }
    } catch {
      setError("Network error");
    }
    setSaving(false);
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-panel rounded-xl2 border border-line p-6 w-[420px] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold text-ink mb-4">
          {t("session:serviceConfig.addProvider")}
        </h3>
        <div className="space-y-3">
          <Field
            label={t("session:serviceConfig.providerName")}
            value={name}
            onChange={setName}
            placeholder="my-aws"
          />
          <SelectField
            label={t("session:serviceConfig.providerType")}
            value={provider}
            onChange={setProvider}
            options={[
              { value: "aws", label: "AWS" },
              { value: "cloudflare", label: "Cloudflare" },
              { value: "wasabi", label: "Wasabi" },
              { value: "gcp", label: "Google Cloud" },
              { value: "azure", label: "Azure" },
            ]}
          />
          <Field
            label="API Key"
            value={apiKey}
            onChange={setApiKey}
            placeholder="AKIA..."
          />
          <Field
            label="API Secret"
            value={apiSecret}
            onChange={setApiSecret}
            type="password"
          />
          <Field
            label={t("session:serviceConfig.region")}
            value={region}
            onChange={setRegion}
            placeholder="us-east-1"
          />
        </div>
        {error && <p className="text-[12px] text-err mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button
            className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted"
            onClick={onClose}
          >
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
  );
}

// ---------------------------------------------------------------------------
// Delete Confirmation (reused from OpsView pattern)
// ---------------------------------------------------------------------------
function DeleteConfirm({
  name,
  onConfirm,
  onCancel,
}: {
  name: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
      onClick={onCancel}
    >
      <div
        className="bg-panel rounded-xl2 border border-line p-5 w-[340px]"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="text-[14px] text-ink mb-4">
          Delete <strong>{name}</strong>?
        </p>
        <div className="flex justify-end gap-2">
          <button
            className="text-[13px] px-3 py-1.5 rounded-lg border border-line text-muted"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="text-[13px] px-3 py-1.5 rounded-lg bg-err text-white font-medium"
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
export function ServiceConfigView() {
  const { t } = useTranslation(["session", "common"]);
  const [tab, setTab] = useState<Tab>("ssh");
  const [sshServers, setSshServers] = useState<SshServer[]>([]);
  const [databases, setDatabases] = useState<DatabaseConfig[]>([]);
  const [cloudProviders, setCloudProviders] = useState<CloudProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showMasked, setShowMasked] = useState<Set<string>>(new Set());
  const [cloudModalOpen, setCloudModalOpen] = useState(false);
  const [expiringCreds, setExpiringCreds] = useState<ExpiringCredential[]>([]);

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [modalType, setModalType] = useState<"ssh" | "db">("ssh");
  const [editItem, setEditItem] = useState<SshServer | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: "ssh" | "db";
    id: string;
    name: string;
  } | null>(null);

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

  const fetchCloudProviders = useCallback(() => {
    setLoading(true);
    fetch("/v1/cloud/providers")
      .then((r) => (r.ok ? r.json() : { providers: [] }))
      .then((data) => setCloudProviders(Array.isArray(data.providers) ? data.providers : []))
      .catch(() => setCloudProviders([]))
      .finally(() => setLoading(false));
  }, []);

  const testCloudProvider = useCallback((name: string) => {
    setCloudProviders((prev) =>
      prev.map((cp) => (cp.name === name ? { ...cp, testing: true, testResult: undefined } : cp)),
    );
    fetch(`/v1/cloud/providers/${encodeURIComponent(name)}/test`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        setCloudProviders((prev) =>
          prev.map((cp) =>
            cp.name === name
              ? { ...cp, testing: false, testResult: data.ok ? "ok" : data.error || "failed" }
              : cp,
          ),
        );
      })
      .catch(() => {
        setCloudProviders((prev) =>
          prev.map((cp) => (cp.name === name ? { ...cp, testing: false, testResult: "error" } : cp)),
        );
      });
  }, []);

  const removeCloudProvider = useCallback(
    (name: string) => {
      fetch(`/v1/cloud/providers/${encodeURIComponent(name)}`, { method: "DELETE" })
        .then(() => fetchCloudProviders())
        .catch(() => {});
    },
    [fetchCloudProviders],
  );

  // Fetch expiring credentials on mount
  useEffect(() => {
    fetch("/v1/vault/expiring?days=30")
      .then((r) => r.json())
      .then((d) => setExpiringCreds(d.expiring || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (tab === "ssh") fetchSsh();
    else if (tab === "database") fetchDatabases();
    else if (tab === "cloud") fetchCloudProviders();
    else setLoading(false);
  }, [tab, fetchSsh, fetchDatabases, fetchCloudProviders]);

  // Modal open helpers
  const openSshAdd = () => {
    setModalType("ssh");
    setEditItem(null);
    setModalOpen(true);
  };

  const openSshEdit = (server: SshServer) => {
    setModalType("ssh");
    setEditItem(server);
    setModalOpen(true);
  };

  const openDbAdd = () => {
    setModalType("db");
    setEditItem(null);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditItem(null);
  };

  // Delete handlers
  const handleDelete = async () => {
    if (!deleteConfirm) return;
    try {
      if (deleteConfirm.type === "ssh") {
        await fetch(
          `/v1/ssh/servers/${encodeURIComponent(deleteConfirm.id)}`,
          { method: "DELETE" },
        );
        fetchSsh();
      } else {
        await fetch(
          `/v1/databases/${encodeURIComponent(deleteConfirm.id)}`,
          { method: "DELETE" },
        );
        fetchDatabases();
      }
    } catch {
      /* ignore */
    }
    setDeleteConfirm(null);
  };

  const tabs: { key: Tab; labelKey: string }[] = [
    { key: "ssh", labelKey: "session:serviceConfig.sshTab" },
    { key: "database", labelKey: "session:serviceConfig.databaseTab" },
    { key: "cloud", labelKey: "session:serviceConfig.cloudTab" },
  ];

  const serviceRow = (
    id: string,
    title: string,
    subtitle: string,
    status: string | undefined,
    onEdit: (() => void) | null,
    onRemove: () => void,
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
      {onEdit && (
        <button
          className="text-[11px] text-accent font-medium"
          onClick={onEdit}
        >
          {t("common:button.edit")}
        </button>
      )}
      <button
        className="text-[11px] text-danger font-medium"
        onClick={onRemove}
      >
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

          {/* Export / Import buttons */}
          <div className="flex items-center gap-2 mb-4">
            <button
              className={BTN_BORDERED}
              onClick={() => {
                fetch("/v1/config/export", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({}),
                })
                  .then((r) => r.json())
                  .then((data) => {
                    if (data.ok) {
                      const blob = new Blob([JSON.stringify(data.config, null, 2)], {
                        type: "application/json",
                      });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = "werubworker-config.json";
                      a.click();
                      URL.revokeObjectURL(url);
                    }
                  })
                  .catch(() => {});
              }}
            >
              <Icon name="file" size={13} className="inline mr-1" />
              {t("session:serviceConfig.exportConfig")}
            </button>
            <button
              className={BTN_BORDERED}
              onClick={() => {
                const input = document.createElement("input");
                input.type = "file";
                input.accept = ".json";
                input.onchange = () => {
                  const file = input.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => {
                    try {
                      const config = JSON.parse(reader.result as string);
                      fetch("/v1/config/import", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ config }),
                      })
                        .then((r) => r.json())
                        .then((data) => {
                          if (data.ok) {
                            const total =
                              (data.imported?.ssh || 0) +
                              (data.imported?.databases || 0) +
                              (data.imported?.cloud || 0);
                            alert(t("session:serviceConfig.importSuccess", { count: total }));
                            if (tab === "ssh") fetchSsh();
                            else if (tab === "database") fetchDatabases();
                            else if (tab === "cloud") fetchCloudProviders();
                          }
                        });
                    } catch {
                      /* ignore parse errors */
                    }
                  };
                  reader.readAsText(file);
                };
                input.click();
              }}
            >
              <Icon name="file" size={13} className="inline mr-1" />
              {t("session:serviceConfig.importConfig")}
            </button>
          </div>

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
                <button className={BTN_ACCENT} onClick={openSshAdd}>
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
                      undefined,
                      () => openSshEdit(s),
                      () =>
                        setDeleteConfirm({
                          type: "ssh",
                          id: s.id,
                          name: s.name || s.host,
                        }),
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
                <button className={BTN_ACCENT} onClick={openDbAdd}>
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
                      undefined,
                      null,
                      () =>
                        setDeleteConfirm({
                          type: "db",
                          id: d.name,
                          name: d.name || d.database || d.host,
                        }),
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
                <button className={BTN_ACCENT} onClick={() => setCloudModalOpen(true)}>
                  + {t("common:button.connect")}
                </button>
              </div>
              {cloudProviders.length === 0 ? (
                <p className="text-[13px] text-muted">
                  {t("session:serviceConfig.noItems")}
                </p>
              ) : (
                <div className="space-y-2">
                  {cloudProviders.map((cp) => (
                    <div
                      key={cp.name}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-paper border border-line"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-ink">
                          {cp.name}
                        </div>
                        <div className="text-[11.5px] text-faint">
                          {cp.provider}{cp.region ? ` (${cp.region})` : ""}
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
                      {cp.testResult && (
                        <span
                          className={
                            "text-[10px] px-2 py-0.5 rounded-full font-medium " +
                            (cp.testResult === "ok"
                              ? "bg-ok/10 text-ok"
                              : "bg-danger/10 text-danger")
                          }
                        >
                          {cp.testResult === "ok" ? t("session:serviceConfig.testOk") : cp.testResult}
                        </span>
                      )}
                      <button
                        className={BTN_BORDERED}
                        onClick={() => testCloudProvider(cp.name)}
                        disabled={cp.testing}
                      >
                        {cp.testing ? t("common:status.loading") : t("session:serviceConfig.test")}
                      </button>
                      <button
                        className="text-[11px] text-danger font-medium"
                        onClick={() => removeCloudProvider(cp.name)}
                      >
                        {t("common:button.remove")}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Rotation badges for expiring credentials */}
          <RotationBadge expiring={expiringCreds} />

          {/* Audit Log */}
          <AuditLogSection />
        </div>
      </div>

      {/* SSH Modal */}
      {modalOpen && modalType === "ssh" && (
        <SshModal
          server={editItem as SshServer | null}
          onClose={closeModal}
          onSaved={fetchSsh}
        />
      )}

      {/* Database Modal */}
      {modalOpen && modalType === "db" && (
        <DatabaseModal onClose={closeModal} onSaved={fetchDatabases} />
      )}

      {/* Cloud Provider Modal */}
      {cloudModalOpen && (
        <CloudModal
          onClose={() => setCloudModalOpen(false)}
          onSaved={fetchCloudProviders}
        />
      )}

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <DeleteConfirm
          name={deleteConfirm.name}
          onConfirm={handleDelete}
          onCancel={() => setDeleteConfirm(null)}
        />
      )}
    </main>
  );
}
