import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelHead } from "./IntegrationsView";
import { Icon } from "./Icon";
import { SchemaTree } from "./SchemaTree";

const CARD = "rounded-xl2 border border-line bg-panel";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

interface DatabaseConfig {
  id: string;
  name: string;
  type: string;
  host: string;
  port?: number;
  database?: string;
  status?: string;
}

interface QueryResult {
  columns: string[];
  rows: string[][];
  rowCount: number;
  totalFetched?: number;
  error?: string;
}

interface MigrationResult {
  ok: boolean;
  table?: string;
  rows?: Record<string, unknown>[];
  message?: string;
  error?: string;
}

interface TableInfo {
  name: string;
  row_count?: number;
}

interface DbStatus {
  ok: boolean;
  type?: string;
  version?: string;
  size?: string;
  size_bytes?: number;
  connections?: number | string;
  table_count?: number;
  host?: string;
  port?: string | number;
  database?: string;
  user?: string;
}

export function DatabaseView() {
  const { t } = useTranslation(["session", "common"]);
  const [databases, setDatabases] = useState<DatabaseConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDb, setSelectedDb] = useState<string>("");
  const [query, setQuery] = useState("");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [executing, setExecuting] = useState(false);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [backingUp, setBackingUp] = useState(false);
  const [backupToast, setBackupToast] = useState(false);
  const [queryHistory, setQueryHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 100;
  const [dbStatus, setDbStatus] = useState<DbStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [migrations, setMigrations] = useState<MigrationResult | null>(null);
  const [migrationsLoading, setMigrationsLoading] = useState(false);
  const [erdMermaid, setErdMermaid] = useState<string | null>(null);
  const [erdLoading, setErdLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchDatabases = useCallback(() => {
    setLoading(true);
    fetch("/v1/databases")
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        const list = Array.isArray(data) ? data : [];
        setDatabases(list);
        if (list.length > 0 && !selectedDb) setSelectedDb(list[0].id);
      })
      .catch(() => setDatabases([]))
      .finally(() => setLoading(false));
  }, [selectedDb]);

  useEffect(() => {
    fetchDatabases();
  }, [fetchDatabases]);

  // Fetch tables when a database is selected
  const fetchTables = useCallback((dbName: string) => {
    if (!dbName) {
      setTables([]);
      return;
    }
    setTablesLoading(true);
    fetch(`/v1/databases/${encodeURIComponent(dbName)}/tables`)
      .then((r) => (r.ok ? r.json() : { ok: false }))
      .then((data) => {
        if (data.ok && Array.isArray(data.tables)) {
          setTables(data.tables);
        } else {
          setTables([]);
        }
      })
      .catch(() => setTables([]))
      .finally(() => setTablesLoading(false));
  }, []);

  // Fetch DB status when a database is selected
  const fetchDbStatus = useCallback((dbName: string) => {
    if (!dbName) {
      setDbStatus(null);
      return;
    }
    setStatusLoading(true);
    fetch(`/v1/databases/${encodeURIComponent(dbName)}/status`)
      .then((r) => (r.ok ? r.json() : { ok: false }))
      .then((data) => {
        if (data.ok) {
          setDbStatus(data);
        } else {
          setDbStatus(null);
        }
      })
      .catch(() => setDbStatus(null))
      .finally(() => setStatusLoading(false));
  }, []);

  const fetchMigrations = useCallback((dbName: string) => {
    if (!dbName) {
      setMigrations(null);
      return;
    }
    setMigrationsLoading(true);
    fetch(`/v1/databases/${encodeURIComponent(dbName)}/migrations`)
      .then((r) => (r.ok ? r.json() : { ok: false }))
      .then((data) => setMigrations(data))
      .catch(() => setMigrations(null))
      .finally(() => setMigrationsLoading(false));
  }, []);

  const fetchErd = useCallback((dbName: string) => {
    if (!dbName) return;
    setErdLoading(true);
    setErdMermaid(null);
    fetch(`/v1/databases/${encodeURIComponent(dbName)}/erd`)
      .then((r) => (r.ok ? r.json() : { ok: false }))
      .then((data) => {
        if (data.ok && data.mermaid) {
          setErdMermaid(data.mermaid);
        }
      })
      .catch(() => setErdMermaid(null))
      .finally(() => setErdLoading(false));
  }, []);

  useEffect(() => {
    if (selectedDb) {
      fetchTables(selectedDb);
      fetchDbStatus(selectedDb);
      fetchMigrations(selectedDb);
    } else {
      setTables([]);
      setDbStatus(null);
      setMigrations(null);
      setErdMermaid(null);
    }
  }, [selectedDb, fetchTables, fetchDbStatus, fetchMigrations]);

  const addToHistory = (q: string) => {
    setQueryHistory((prev) => {
      const filtered = prev.filter((h) => h !== q);
      return [q, ...filtered].slice(0, 20);
    });
  };

  const executeQuery = (pageOverride?: number) => {
    if (!query.trim() || !selectedDb) return;
    const currentPage = pageOverride ?? 0;
    setExecuting(true);
    setQueryResult(null);
    setErrorMsg(null);
    setPage(currentPage);

    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // 30-second timeout
    const timeoutId = setTimeout(() => controller.abort(), 30_000);

    if (pageOverride === undefined) addToHistory(query.trim());

    fetch(`/v1/databases/${encodeURIComponent(selectedDb)}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query.trim(),
        offset: currentPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setQueryResult({ columns: [], rows: [], rowCount: 0, error: data.error });
          setErrorMsg(data.error);
        } else {
          setQueryResult({
            columns: data.columns || [],
            rows: data.rows || [],
            rowCount: data.row_count ?? (data.rows || []).length,
            totalFetched: data.total_fetched,
          });
        }
      })
      .catch((err) => {
        const isTimeout = err.name === "AbortError";
        const message = isTimeout
          ? t("session:database.queryTimeout")
          : String(err);
        setQueryResult({
          columns: [],
          rows: [],
          rowCount: 0,
          error: message,
        });
        setErrorMsg(message);
      })
      .finally(() => {
        clearTimeout(timeoutId);
        setExecuting(false);
        abortRef.current = null;
      });
  };

  const requestBackup = () => {
    if (!selectedDb) return;
    setBackingUp(true);
    setBackupToast(false);
    fetch("/v1/databases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ database_id: selectedDb, action: "backup" }),
    })
      .then(() => {
        setBackupToast(true);
        setTimeout(() => setBackupToast(false), 3000);
      })
      .catch(() => {})
      .finally(() => {
        setTimeout(() => setBackingUp(false), 2000);
      });
  };

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:database.title")}
            sub={t("session:database.sub")}
          />

          {/* Database selector */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:database.configured")}
              </h3>
              <button
                className="text-[12.5px] text-accent font-medium"
                onClick={fetchDatabases}
              >
                <Icon name="refresh" size={13} className="inline mr-1" />
                {t("common:button.refresh")}
              </button>
            </div>
            {loading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : databases.length === 0 ? (
              <p className="text-[13px] text-muted">
                {t("session:database.noDatabases")}
              </p>
            ) : (
              <div className="space-y-2">
                {databases.map((db) => (
                  <div
                    key={db.id}
                    className={
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors " +
                      (selectedDb === db.id
                        ? "bg-accentSoft/30 border-accent"
                        : "bg-paper border-line hover:border-lineStrong")
                    }
                    onClick={() => setSelectedDb(db.id)}
                  >
                    <Icon name="table" size={15} className="text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium text-ink truncate">
                        {db.name || db.database || db.host}
                      </div>
                      <div className="text-[11.5px] text-faint truncate">
                        {db.type}://{db.host}:{db.port ?? ""}/{db.database ?? ""}
                      </div>
                    </div>
                    <span
                      className={
                        "text-[11px] px-2 py-0.5 rounded-full font-medium " +
                        (db.status === "connected"
                          ? "bg-ok/10 text-ok"
                          : "bg-faint/10 text-faint")
                      }
                    >
                      {db.status || "configured"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* DB Status card */}
          {selectedDb && dbStatus && (
            <div className={CARD + " p-5 mb-4"}>
              <h3 className="text-[14px] font-semibold text-ink mb-3">
                {t("session:database.dbStatus")}
              </h3>
              {statusLoading ? (
                <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {dbStatus.version && (
                    <div>
                      <div className="text-[11px] text-faint">{t("session:database.version")}</div>
                      <div className="text-[13px] text-ink truncate">{String(dbStatus.version).slice(0, 40)}</div>
                    </div>
                  )}
                  {(dbStatus.size || dbStatus.size_bytes != null) && (
                    <div>
                      <div className="text-[11px] text-faint">{t("session:database.size")}</div>
                      <div className="text-[13px] text-ink">
                        {dbStatus.size || `${((dbStatus.size_bytes ?? 0) / 1024).toFixed(1)} KB`}
                      </div>
                    </div>
                  )}
                  {dbStatus.table_count != null && (
                    <div>
                      <div className="text-[11px] text-faint">{t("session:database.tables")}</div>
                      <div className="text-[13px] text-ink">{dbStatus.table_count}</div>
                    </div>
                  )}
                  {dbStatus.connections != null && (
                    <div>
                      <div className="text-[11px] text-faint">{t("session:database.connections")}</div>
                      <div className="text-[13px] text-ink">{String(dbStatus.connections)}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Query runner */}
          <div className={CARD + " p-5 mb-4"}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:database.queryRunner")}
              </h3>
              <div className="flex items-center gap-2">
                {/* Query history dropdown */}
                {queryHistory.length > 0 && (
                  <div className="relative">
                    <button
                      className={BTN_BORDERED}
                      onClick={() => setShowHistory(!showHistory)}
                    >
                      <Icon name="file" size={13} className="inline mr-1" />
                      {t("session:database.queryHistory")}
                    </button>
                    {showHistory && (
                      <div className="absolute right-0 top-full mt-1 w-80 max-h-60 overflow-y-auto rounded-lg border border-line bg-panel shadow-lg z-20">
                        {queryHistory.map((h, i) => (
                          <div
                            key={i}
                            className="px-3 py-2 text-[12px] font-mono text-ink hover:bg-paper cursor-pointer border-b border-line last:border-b-0 truncate"
                            onClick={() => {
                              setQuery(h);
                              setShowHistory(false);
                            }}
                          >
                            {h}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                <button
                  className={BTN_BORDERED}
                  onClick={requestBackup}
                  disabled={!selectedDb || backingUp}
                >
                  {backingUp
                    ? t("common:status.running")
                    : t("session:database.backup")}
                </button>
              </div>
            </div>

            {/* Backup toast */}
            {backupToast && (
              <div className="mb-3 px-3 py-2 rounded-lg bg-ok/10 text-ok text-[12.5px]">
                {t("session:database.backupStarted")}
              </div>
            )}

            <div className="mb-3">
              <div className="text-[11.5px] text-faint mb-1.5 font-medium">
                {t("session:database.sqlEditor")}
              </div>
              <textarea
                className="w-full font-mono text-[12.5px] min-h-[100px] resize-y px-4 py-3 rounded-lg border border-line bg-[#1e1e2e] text-[#cdd6f4] outline-none focus:border-accent caret-[#cdd6f4] placeholder:text-[#585b70] leading-relaxed"
                placeholder={t("session:database.queryPlaceholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                spellCheck={false}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                    e.preventDefault();
                    executeQuery();
                  }
                  // Tab key inserts spaces instead of changing focus
                  if (e.key === "Tab") {
                    e.preventDefault();
                    const target = e.target as HTMLTextAreaElement;
                    const start = target.selectionStart;
                    const end = target.selectionEnd;
                    setQuery(query.substring(0, start) + "  " + query.substring(end));
                    requestAnimationFrame(() => {
                      target.selectionStart = target.selectionEnd = start + 2;
                    });
                  }
                }}
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                className={BTN_ACCENT}
                onClick={() => executeQuery()}
                disabled={!query.trim() || !selectedDb || executing}
              >
                {executing
                  ? t("common:status.running")
                  : t("session:database.execute")}
              </button>
              <span className="text-[11px] text-faint">Ctrl+Enter</span>
            </div>

            {/* Error feedback */}
            {errorMsg && !queryResult?.error && (
              <div className="mt-3 px-3 py-2 rounded-lg bg-danger/10 text-danger text-[12.5px]">
                {errorMsg}
              </div>
            )}

            {/* Results */}
            {queryResult && (
              <div className="mt-4">
                {queryResult.error ? (
                  <div className="px-3 py-2 rounded-lg bg-danger/10 text-danger text-[12.5px]">
                    {queryResult.error}
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[11.5px] text-faint">
                        {t("session:database.page")} {page + 1}
                        {queryResult.totalFetched != null && (
                          <span> &middot; {queryResult.totalFetched} {t("session:database.totalRows")}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          className={BTN_BORDERED + " text-[11px] px-2 py-1"}
                          disabled={page === 0 || executing}
                          onClick={() => executeQuery(page - 1)}
                        >
                          {t("session:database.prevPage")}
                        </button>
                        <button
                          className={BTN_BORDERED + " text-[11px] px-2 py-1"}
                          disabled={queryResult.rows.length < PAGE_SIZE || executing}
                          onClick={() => executeQuery(page + 1)}
                        >
                          {t("session:database.nextPage")}
                        </button>
                      </div>
                    </div>
                    {queryResult.columns.length > 0 && (
                      <div className="overflow-x-auto rounded-lg border border-line">
                        <table className="w-full text-[12px]">
                          <thead>
                            <tr className="bg-paper border-b border-line">
                              {queryResult.columns.map((col, i) => (
                                <th
                                  key={i}
                                  className="px-3 py-1.5 text-left font-semibold text-ink whitespace-nowrap"
                                >
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {queryResult.rows.map((row, ri) => (
                              <tr
                                key={ri}
                                className="border-b border-line last:border-b-0 hover:bg-paper/50"
                              >
                                {row.map((cell, ci) => (
                                  <td
                                    key={ci}
                                    className="px-3 py-1.5 text-muted whitespace-nowrap max-w-[200px] truncate"
                                  >
                                    {cell}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          {/* Schema tree (tables + columns) */}
          <div className={CARD + " p-5"}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[14px] font-semibold text-ink">
                {t("session:database.tables")}
              </h3>
              {tables.length > 0 && (
                <span className="text-[11.5px] text-faint">
                  {t("session:database.tableCount", { count: tables.length })}
                </span>
              )}
            </div>
            {tablesLoading ? (
              <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
            ) : !selectedDb ? (
              <p className="text-[13px] text-muted">
                {t("session:database.noDatabases")}
              </p>
            ) : tables.length === 0 ? (
              <p className="text-[13px] text-muted">
                {t("session:database.noTables")}
              </p>
            ) : (
              <SchemaTree
                dbName={selectedDb}
                tables={tables.map((tbl) => ({
                  table_name: tbl.name,
                  row_count: tbl.row_count ?? 0,
                }))}
                onSelectTable={(name) =>
                  setQuery(`SELECT * FROM ${name} LIMIT 50;`)
                }
              />
            )}
          </div>

          {/* ERD Diagram */}
          {selectedDb && (
            <div className={CARD + " p-5 mt-4"}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[14px] font-semibold text-ink">
                  {t("session:database.erdTitle")}
                </h3>
                <button
                  className={BTN_BORDERED}
                  onClick={() => fetchErd(selectedDb)}
                  disabled={erdLoading}
                >
                  {erdLoading ? t("session:database.erdLoading") : t("session:database.erd")}
                </button>
              </div>
              {erdMermaid && (
                <pre className="text-[12px] font-mono text-muted bg-paper rounded-lg border border-line p-3 overflow-x-auto whitespace-pre max-h-[400px] overflow-y-auto">
                  {erdMermaid}
                </pre>
              )}
            </div>
          )}

          {/* Migrations */}
          {selectedDb && (
            <div className={CARD + " p-5 mt-4"}>
              <h3 className="text-[14px] font-semibold text-ink mb-3">
                {t("session:database.migrations")}
              </h3>
              {migrationsLoading ? (
                <p className="text-[13px] text-muted">{t("common:status.loading")}</p>
              ) : !migrations || migrations.error ? (
                <p className="text-[13px] text-muted">
                  {migrations?.error || t("session:database.noMigrations")}
                </p>
              ) : !migrations.rows || migrations.rows.length === 0 ? (
                <p className="text-[13px] text-muted">
                  {migrations.message || t("session:database.noMigrations")}
                </p>
              ) : (
                <>
                  {migrations.table && (
                    <div className="text-[11.5px] text-faint mb-2">
                      {t("session:database.migrationTable")}: <span className="font-mono">{migrations.table}</span>
                    </div>
                  )}
                  <div className="overflow-x-auto rounded-lg border border-line">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr className="bg-paper border-b border-line">
                          {Object.keys(migrations.rows[0]).map((col) => (
                            <th
                              key={col}
                              className="px-3 py-1.5 text-left font-semibold text-ink whitespace-nowrap"
                            >
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {migrations.rows.map((row, ri) => (
                          <tr
                            key={ri}
                            className="border-b border-line last:border-b-0 hover:bg-paper/50"
                          >
                            {Object.values(row).map((cell, ci) => (
                              <td
                                key={ci}
                                className="px-3 py-1.5 text-muted whitespace-nowrap max-w-[200px] truncate"
                              >
                                {String(cell ?? "")}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
