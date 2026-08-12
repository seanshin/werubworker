import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

interface ColumnInfo {
  column_name?: string;
  Field?: string;
  name?: string;
  data_type?: string;
  Type?: string;
  type?: string;
  is_nullable?: string;
  notnull?: number;
  Null?: string;
  dflt_value?: string;
  column_default?: string;
  Default?: string;
}

interface IndexInfo {
  indexname?: string;
  indexdef?: string;
  name?: string;
  Key_name?: string;
  seq?: number;
  unique?: number;
}

export interface SchemaTreeProps {
  dbName: string;
  tables: { table_name?: string; name?: string; row_count: number | string }[];
  onSelectTable: (table: string) => void;
}

function normalizeColumnName(col: ColumnInfo): string {
  return col.column_name || col.Field || col.name || "";
}

function normalizeColumnType(col: ColumnInfo): string {
  return col.data_type || col.Type || col.type || "";
}

function normalizeNullable(col: ColumnInfo): string {
  if (col.is_nullable !== undefined) return col.is_nullable;
  if (col.notnull !== undefined) return col.notnull ? "NO" : "YES";
  if (col.Null !== undefined) return col.Null;
  return "";
}

export function SchemaTree({ dbName, tables, onSelectTable }: SchemaTreeProps) {
  const { t } = useTranslation(["session", "common"]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [columns, setColumns] = useState<Record<string, ColumnInfo[]>>({});
  const [indexes, setIndexes] = useState<Record<string, IndexInfo[]>>({});
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [showIndexes, setShowIndexes] = useState<Set<string>>(new Set());

  const toggleTable = useCallback(
    (tableName: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(tableName)) {
          next.delete(tableName);
        } else {
          next.add(tableName);
          // Fetch columns if not already loaded
          if (!columns[tableName]) {
            setLoading((l) => new Set(l).add(tableName));
            fetch(
              `/v1/databases/${encodeURIComponent(dbName)}/tables/${encodeURIComponent(tableName)}/columns`,
            )
              .then((r) => (r.ok ? r.json() : { ok: false }))
              .then((data) => {
                if (data.ok && Array.isArray(data.rows)) {
                  setColumns((prev) => ({ ...prev, [tableName]: data.rows }));
                }
              })
              .catch(() => {})
              .finally(() =>
                setLoading((l) => {
                  const n = new Set(l);
                  n.delete(tableName);
                  return n;
                }),
              );
          }
        }
        return next;
      });
    },
    [dbName, columns],
  );

  const toggleIndexes = useCallback(
    (tableName: string) => {
      setShowIndexes((prev) => {
        const next = new Set(prev);
        if (next.has(tableName)) {
          next.delete(tableName);
        } else {
          next.add(tableName);
          if (!indexes[tableName]) {
            fetch(
              `/v1/databases/${encodeURIComponent(dbName)}/tables/${encodeURIComponent(tableName)}/indexes`,
            )
              .then((r) => (r.ok ? r.json() : { ok: false }))
              .then((data) => {
                if (data.ok && Array.isArray(data.rows)) {
                  setIndexes((prev) => ({ ...prev, [tableName]: data.rows }));
                }
              })
              .catch(() => {});
          }
        }
        return next;
      });
    },
    [dbName, indexes],
  );

  return (
    <div className="space-y-0.5">
      {tables.map((tbl) => {
        const name = tbl.table_name || tbl.name || "";
        const isExpanded = expanded.has(name);
        const isLoading = loading.has(name);
        const cols = columns[name];
        const idxs = indexes[name];
        const idxVisible = showIndexes.has(name);

        return (
          <div key={name}>
            {/* Table row */}
            <div
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-paper cursor-pointer text-[13px] text-ink group"
              onClick={() => {
                toggleTable(name);
                onSelectTable(name);
              }}
            >
              <Icon
                name={isExpanded ? "chevronDown" : "chevronRight"}
                size={11}
                className="text-faint shrink-0"
              />
              <Icon name="file" size={13} className="text-faint shrink-0" />
              <span className="flex-1 min-w-0 truncate">{name}</span>
              {tbl.row_count != null && (
                <span className="text-[11px] text-faint shrink-0">
                  {tbl.row_count} {t("session:database.rows")}
                </span>
              )}
            </div>

            {/* Expanded: columns */}
            {isExpanded && (
              <div className="ml-7 border-l border-line pl-2">
                {isLoading ? (
                  <div className="px-3 py-1 text-[11.5px] text-muted">
                    {t("common:status.loading")}
                  </div>
                ) : cols && cols.length > 0 ? (
                  <>
                    {cols.map((col, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 px-2 py-0.5 text-[12px] text-muted"
                      >
                        <span className="text-ink font-medium min-w-0 truncate">
                          {normalizeColumnName(col)}
                        </span>
                        <span className="text-faint text-[11px] shrink-0">
                          {normalizeColumnType(col)}
                        </span>
                        {normalizeNullable(col) === "YES" && (
                          <span className="text-[10px] text-faint bg-faint/10 px-1 rounded shrink-0">
                            {t("session:database.nullable")}
                          </span>
                        )}
                      </div>
                    ))}
                    {/* Indexes toggle */}
                    <div
                      className="flex items-center gap-1 px-2 py-1 mt-0.5 text-[11px] text-accent cursor-pointer hover:underline"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleIndexes(name);
                      }}
                    >
                      <Icon
                        name={idxVisible ? "chevronDown" : "chevronRight"}
                        size={10}
                      />
                      {t("session:database.indexes")}
                    </div>
                    {idxVisible && idxs && idxs.length > 0 && (
                      <div className="ml-2 mb-1">
                        {idxs.map((idx, i) => (
                          <div
                            key={i}
                            className="text-[11px] text-faint px-2 py-0.5 truncate"
                          >
                            {idx.indexname || idx.name || idx.Key_name || `index-${i}`}
                            {idx.unique ? " (unique)" : ""}
                          </div>
                        ))}
                      </div>
                    )}
                    {idxVisible && (!idxs || idxs.length === 0) && (
                      <div className="ml-2 mb-1 text-[11px] text-faint px-2">
                        {t("session:database.noIndexes")}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="px-3 py-1 text-[11.5px] text-muted">
                    {t("session:database.noColumns")}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
