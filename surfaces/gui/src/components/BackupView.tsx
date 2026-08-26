import { useCallback, useEffect, useState } from "react";
import { formatDateTime, fromEpoch } from "../formatDate";
import { useTranslation } from "react-i18next";

const CARD = "rounded-xl2 border border-line bg-panel";

interface BackupRecord {
  id: string;
  timestamp: number;
  targets: string[];
  size_human: string;
  status: string;
  error: string;
}

interface BackupTarget {
  name: string;
  file: string;
  exists: boolean;
  size_human: string;
}

function backupDate(epoch: number): string {
  if (!epoch) return "\u2014";
  return formatDateTime(fromEpoch(epoch), { hour12: false });
}

export function BackupView() {
  const { t } = useTranslation(["session"]);
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [targets, setTargets] = useState<BackupTarget[]>([]);
  const [selectedTargets, setSelectedTargets] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);

  const fetchBackups = useCallback(() => {
    fetch("/v1/dashboard/backups")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setBackups(d.backups || []); })
      .catch(() => {});
  }, []);

  const fetchTargets = useCallback(() => {
    fetch("/v1/dashboard/backups/targets")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.ok) setTargets(d.targets || []); })
      .catch(() => {});
  }, []);

  useEffect(() => { fetchBackups(); fetchTargets(); }, [fetchBackups, fetchTargets]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const body = selectedTargets.length > 0 ? { targets: selectedTargets } : {};
      await fetch("/v1/dashboard/backups", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      fetchBackups();
    } catch { /* ignore */ }
    setCreating(false);
  };

  const handleRestore = async (backupId: string) => {
    if (!confirm(t("session:backup.restoreConfirm"))) return;
    setRestoring(backupId);
    try {
      await fetch(`/v1/dashboard/backups/${backupId}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      alert(t("session:backup.restoreDone"));
    } catch { /* ignore */ }
    setRestoring(null);
  };

  const handleDelete = async (backupId: string) => {
    if (!confirm(t("session:backup.deleteConfirm"))) return;
    await fetch(`/v1/dashboard/backups/${backupId}`, { method: "DELETE" });
    fetchBackups();
  };

  const toggleTarget = (name: string) => {
    setSelectedTargets((prev) => prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]);
  };

  return (
    <div className="flex flex-col gap-4 p-4 overflow-auto">
      <h2 className="text-lg font-semibold">{t("session:backup.title")}</h2>

      {/* Targets & Create */}
      <div className={CARD + " p-4"}>
        <h3 className="font-semibold text-sm mb-3">{t("session:backup.targets")}</h3>
        <div className="grid grid-cols-4 gap-2 mb-3">
          {targets.map((target) => (
            <label key={target.name} className={`flex items-center gap-2 text-xs p-2 rounded cursor-pointer ${target.exists ? "bg-paper" : "bg-paper/50 opacity-50"}`}>
              <input type="checkbox" checked={selectedTargets.includes(target.name)} onChange={() => toggleTarget(target.name)} disabled={!target.exists} />
              <span className="font-medium">{target.name}</span>
              <span className="text-muted ml-auto">{target.size_human}</span>
            </label>
          ))}
        </div>
        <button onClick={handleCreate} disabled={creating}
          className="text-xs px-3 py-1.5 rounded bg-accent text-white hover:bg-accent/90 disabled:opacity-50">
          {creating
            ? t("session:backup.creating")
            : selectedTargets.length > 0
              ? t("session:backup.createSelected", { count: selectedTargets.length })
              : t("session:backup.create")}
        </button>
      </div>

      {/* Backup List */}
      <div className={CARD + " p-4"}>
        <h3 className="font-semibold text-sm mb-3">{t("session:backup.history")}</h3>
        {backups.length === 0 ? (
          <div className="text-xs text-muted py-4 text-center">{t("session:backup.empty")}</div>
        ) : (
          <div className="space-y-2">
            {backups.map((b) => (
              <div key={b.id} className="flex items-center gap-3 text-xs p-2 rounded bg-paper">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${b.status === "completed" ? "bg-green-500" : b.status === "partial" ? "bg-yellow-500" : "bg-red-500"}`}>
                  {t(`session:backup.status${b.status === "completed" ? "Completed" : b.status === "partial" ? "Partial" : "Failed"}`)}
                </span>
                <span className="text-muted">{backupDate(b.timestamp)}</span>
                <span className="text-muted">{b.size_human}</span>
                <span className="flex-1 truncate">{b.targets.join(", ")}</span>
                <div className="flex gap-1">
                  <button onClick={() => handleRestore(b.id)} disabled={restoring === b.id}
                    className="px-2 py-0.5 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50">
                    {restoring === b.id ? t("session:backup.restoring") : t("session:backup.restore")}
                  </button>
                  <button onClick={() => handleDelete(b.id)}
                    className="px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20">{t("session:backup.delete")}</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
