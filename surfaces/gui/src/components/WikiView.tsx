import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getWikiPages, getWikiCategories, getWikiAlerts } from "../api";
import { PanelHead } from "./IntegrationsView";
import { WikiPageView } from "./WikiPageView";
import { WikiPageEditor } from "./WikiPageEditor";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";

interface WikiPage {
  id: string;
  name: string;
  category: string;
  tags: string[];
  updated_at?: string;
  linked_service?: string;
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
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [activePageId, setActivePageId] = useState<string | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    Promise.all([
      getWikiPages(query || undefined, selectedCategory || undefined).catch(
        () => [],
      ),
      getWikiCategories().catch(() => []),
      getWikiAlerts().catch(() => []),
    ])
      .then(([p, c, a]) => {
        setPages(Array.isArray(p) ? p : (p as any)?.pages || []);
        setCategories(
          Array.isArray(c) ? c : (c as any)?.categories || [],
        );
        setAlerts(Array.isArray(a) ? a : (a as any)?.alerts || []);
      })
      .finally(() => setLoading(false));
  }, [query, selectedCategory]);

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

        {/* Recently modified list */}
        <div>
          <h3 className="text-[13px] font-semibold mb-2">
            {t("session:wiki.recentlyModified")}
          </h3>
          {loading ? (
            <div className="text-[12.5px] text-muted py-4 text-center">
              Loading...
            </div>
          ) : pages.length === 0 ? (
            <div className={CARD + " p-6 text-center text-[13px] text-muted"}>
              {t("session:wiki.noPages")}
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
                  <Icon name="book" size={16} className="text-muted shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium text-ink truncate">
                      {page.name}
                    </div>
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
