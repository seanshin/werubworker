import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getWikiPages, getWikiCategories, getWikiAlerts, searchWiki } from "../api";
import { PanelHead } from "./IntegrationsView";
import { WikiPageView } from "./WikiPageView";
import { WikiPageEditor } from "./WikiPageEditor";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";

// LLM wiki extended categories → available IconName values
import type { IconName } from "./Icon";
const CATEGORY_ICONS: Record<string, IconName> = {
  service: "wrench",
  database: "table",
  server: "wrench",
  cloud: "plug",
  general: "book",
  model: "sparkle",
  prompt: "pencil",
  benchmark: "diamond",
  runbook: "file",
  api_doc: "code",
  architecture: "folder",
};

interface WikiPage {
  id: string;
  page_id?: string;
  name: string;
  category: string;
  tags: string[];
  updated_at?: string | number;
  linked_service?: string;
  snippet?: string;
}

/** Normalize page data — API returns page_id, UI uses id */
function normalizePage(p: any): WikiPage {
  return {
    ...p,
    id: p.id || p.page_id || "",
    updated_at: typeof p.updated_at === "number"
      ? new Date(p.updated_at * 1000).toISOString()
      : p.updated_at,
  };
}

interface WikiAlert {
  page_id: string;
  page_name: string;
  credential_key: string;
  credential_label: string;
  days_left: number;
  type: string;
}

type ViewMode = "list" | "view" | "edit" | "new";

export function WikiView() {
  const { t } = useTranslation(["session"]);

  const [pages, setPages] = useState<WikiPage[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<WikiAlert[]>([]);
  const [loading, setLoading] = useState(true);

  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [activePageId, setActivePageId] = useState<string | null>(null);

  // Debounce search query (300ms)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedQuery(query), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  const isSearchMode = debouncedQuery.trim().length > 0;

  const fetchData = useCallback(() => {
    setLoading(true);
    if (isSearchMode) {
      // FTS search mode — skip category filter and alerts
      searchWiki(debouncedQuery.trim())
        .catch(() => [])
        .then((results) => {
          const mapped = (results as any[]).map((r) => normalizePage({
            id: r.page_id ?? r.id,
            name: r.name,
            category: r.category,
            tags: r.tags ?? [],
            updated_at: r.updated_at,
            snippet: r.snippet,
          }));
          setPages(mapped);
        })
        .finally(() => setLoading(false));
    } else {
      Promise.all([
        getWikiPages(undefined, selectedCategory || undefined).catch(
          () => [],
        ),
        getWikiCategories().catch(() => []),
        getWikiAlerts().catch(() => []),
      ])
        .then(([p, c, a]) => {
          const raw = Array.isArray(p) ? p : (p as any)?.pages || [];
          setPages(raw.map(normalizePage));
          setCategories(
            Array.isArray(c) ? c : (c as any)?.categories || [],
          );
          setAlerts(Array.isArray(a) ? a : (a as any)?.alerts || []);
        })
        .finally(() => setLoading(false));
    }
  }, [debouncedQuery, selectedCategory, isSearchMode]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openPage = (id: string) => {
    setActivePageId(id);
    setViewMode("view");
  };

  const editPage = (id: string) => {
    setActivePageId(id);
    setViewMode("edit");
  };

  const newPage = () => {
    setActivePageId(null);
    setViewMode("new");
  };

  const backToList = () => {
    setViewMode("list");
    setActivePageId(null);
    fetchData();
  };

  // Sub-views
  if (viewMode === "view" && activePageId) {
    return (
      <div className="manage-surface overflow-y-auto">
        <div className="px-8 py-6">
          <WikiPageView
            pageId={activePageId}
            onBack={backToList}
            onEdit={editPage}
          />
        </div>
      </div>
    );
  }

  if (viewMode === "edit" || viewMode === "new") {
    return (
      <div className="manage-surface overflow-y-auto">
        <div className="px-8 py-6">
          <PanelHead
            title={
              viewMode === "new"
                ? t("session:wiki.newDoc")
                : t("session:wiki.edit")
            }
            sub={t("session:wiki.subtitle")}
          />
          <WikiPageEditor
            pageId={activePageId}
            onSave={backToList}
            onCancel={backToList}
          />
        </div>
      </div>
    );
  }

  // List view
  return (
    <div className="manage-surface overflow-y-auto">
      <div className="px-8 py-6 max-w-4xl mx-auto space-y-5">
        <div className="flex items-start justify-between">
          <PanelHead
            title={t("session:wiki.title")}
            sub={t("session:wiki.subtitle")}
          />
          <button
            className="text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 flex items-center gap-1.5"
            onClick={newPage}
          >
            <Icon name="plus" size={14} />
            {t("session:wiki.newDoc")}
          </button>
        </div>

        {/* Search */}
        <div className="relative">
          <Icon
            name="search"
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <input
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("session:wiki.search")}
          />
        </div>

        {/* Category chips */}
        {categories.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-faint font-semibold uppercase tracking-wide mr-1">
              {t("session:wiki.categories")}
            </span>
            <button
              className={
                "text-[12px] px-2.5 py-1 rounded-full border " +
                (selectedCategory === null
                  ? "border-accent bg-accentSoft text-accent font-medium"
                  : "border-line text-muted hover:text-ink")
              }
              onClick={() => setSelectedCategory(null)}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                className={
                  "text-[12px] px-2.5 py-1 rounded-full border " +
                  (selectedCategory === cat
                    ? "border-accent bg-accentSoft text-accent font-medium"
                    : "border-line text-muted hover:text-ink")
                }
                onClick={() =>
                  setSelectedCategory(selectedCategory === cat ? null : cat)
                }
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className={CARD + " p-4"}>
            <h3 className="text-[13px] font-semibold mb-2 flex items-center gap-1.5">
              <Icon name="info" size={14} className="text-warn" />
              {t("session:wiki.alertsTitle")}
            </h3>
            <div className="space-y-1.5">
              {alerts.map((alert, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 text-[12.5px] cursor-pointer hover:bg-paper rounded-lg px-2 py-1.5"
                  onClick={() => openPage(alert.page_id)}
                >
                  <span className="text-ink font-medium truncate">
                    {alert.page_name}
                  </span>
                  <span className="text-muted truncate">
                    {alert.credential_label}
                  </span>
                  <span
                    className={
                      "ml-auto shrink-0 text-[11px] px-2 py-0.5 rounded-full " +
                      (alert.days_left <= 0
                        ? "bg-danger/10 text-danger font-semibold"
                        : "bg-warn/10 text-warn font-semibold")
                    }
                  >
                    {alert.days_left <= 0
                      ? t("session:wiki.expired")
                      : t("session:wiki.daysLeft", {
                          days: alert.days_left,
                        })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Page list */}
        <div>
          <h3 className="text-[13px] font-semibold mb-2">
            {isSearchMode
              ? t("session:wiki.searchResults")
              : t("session:wiki.recentlyModified")}
          </h3>
          {loading ? (
            <div className="text-[12.5px] text-muted py-4 text-center">
              Loading...
            </div>
          ) : pages.length === 0 ? (
            <div className={CARD + " p-6 text-center text-[13px] text-muted"}>
              {isSearchMode
                ? t("session:wiki.noSearchResults", { query: debouncedQuery })
                : t("session:wiki.noPages")}
            </div>
          ) : (
            <div className="space-y-1">
              {pages.map((page) => (
                <div
                  key={page.id}
                  className={
                    CARD +
                    " px-4 py-3 flex items-center gap-3 cursor-pointer hover:bg-paper/60"
                  }
                  onClick={() => openPage(page.id)}
                >
                  <Icon name={CATEGORY_ICONS[page.category] ?? "book"} size={16} className="text-muted shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-ink truncate">
                      {page.name}
                    </div>
                    {isSearchMode && page.snippet ? (
                      <div
                        className="text-[12px] text-muted mt-0.5 line-clamp-2 [&_mark]:bg-yellow-200/60 [&_mark]:text-ink [&_mark]:rounded-sm"
                        dangerouslySetInnerHTML={{ __html: page.snippet }}
                      />
                    ) : (
                      <div className="flex items-center gap-2 mt-0.5">
                        {page.category && (
                          <span className="text-[11px] text-accent">
                            {page.category}
                          </span>
                        )}
                        {page.tags?.slice(0, 3).map((tag) => (
                          <span
                            key={tag}
                            className="text-[11px] text-faint"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {page.updated_at && (
                    <span className="text-[11px] text-faint tabular-nums shrink-0">
                      {new Date(page.updated_at).toLocaleDateString()}
                    </span>
                  )}
                  <Icon
                    name="chevronRight"
                    size={14}
                    className="text-faint shrink-0"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
