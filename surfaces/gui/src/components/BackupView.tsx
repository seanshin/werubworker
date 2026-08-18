import { useCallback, useEffect, useState } from "react";

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

function formatDate(epoch: number): string {
  if (!epoch) return "\u2014";
  return new Date(epoch * 1000).toLocaleString("ko-KR", { hour12: false });
}

export function BackupView() {
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
    if (!confirm("이 백업에서 복원하시겠습니까? 현재 데이터가 덮어씌워집니다.")) return;
    setRestoring(backupId);
    try {
      await fetch(`/v1/dashboard/backups/${backupId}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      alert("복원 완료. 서비스를 재시작해주세요.");
    } catch { /* ignore */ }
    setRestoring(null);
  };

  const handleDelete = async (backupId: string) => {
    if (!confirm("이 백업을 삭제하시겠습니까?")) return;
    await fetch(`/v1/dashboard/backups/${backupId}`, { method: "DELETE" });
    fetchBackups();
  };

  const toggleTarget = (name: string) => {
    setSelectedTargets((prev) => prev.includes(name) ? prev.filter((t) => t !== name) : [...prev, name]);
  };

  return (
    <div className="flex flex-col gap-4 p-4 overflow-auto">
      <h2 className="text-lg font-semibold">백업 / 복원</h2>

      {/* Targets & Create */}
      <div className={CARD + " p-4"}>
        <h3 className="font-semibold text-sm mb-3">백업 대상</h3>
        <div className="grid grid-cols-4 gap-2 mb-3">
          {targets.map((t) => (
            <label key={t.name} className={`flex items-center gap-2 text-xs p-2 rounded cursor-pointer ${t.exists ? "bg-paper" : "bg-paper/50 opacity-50"}`}>
              <input type="checkbox" checked={selectedTargets.includes(t.name)} onChange={() => toggleTarget(t.name)} disabled={!t.exists} />
              <span className="font-medium">{t.name}</span>
              <span className="text-muted ml-auto">{t.size_human}</span>
            </label>
          ))}
        </div>
        <button onClick={handleCreate} disabled={creating}
          className="text-xs px-3 py-1.5 rounded bg-accent text-white hover:bg-accent/90 disabled:opacity-50">
          {creating ? "백업 중..." : selectedTargets.length > 0 ? `선택 항목 백업 (${selectedTargets.length})` : "전체 백업"}
        </button>
      </div>

      {/* Backup List */}
      <div className={CARD + " p-4"}>
        <h3 className="font-semibold text-sm mb-3">백업 이력</h3>
        {backups.length === 0 ? (
          <div className="text-xs text-muted py-4 text-center">백업 기록이 없습니다</div>
        ) : (
          <div className="space-y-2">
            {backups.map((b) => (
              <div key={b.id} className="flex items-center gap-3 text-xs p-2 rounded bg-paper">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${b.status === "completed" ? "bg-green-500" : b.status === "partial" ? "bg-yellow-500" : "bg-red-500"}`}>
                  {b.status === "completed" ? "완료" : b.status === "partial" ? "부분" : "실패"}
                </span>
                <span className="text-muted">{formatDate(b.timestamp)}</span>
                <span className="text-muted">{b.size_human}</span>
                <span className="flex-1 truncate">{b.targets.join(", ")}</span>
                <div className="flex gap-1">
                  <button onClick={() => handleRestore(b.id)} disabled={restoring === b.id}
                    className="px-2 py-0.5 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50">
                    {restoring === b.id ? "복원 중..." : "복원"}
                  </button>
                  <button onClick={() => handleDelete(b.id)}
                    className="px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20">삭제</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
