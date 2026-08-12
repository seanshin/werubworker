import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getWikiPage, deleteWikiPage } from "../api";
import { Markdown } from "./Markdown";
import { WikiCredentialCard } from "./WikiCredentialCard";
import { WikiPromptEditor } from "./WikiPromptEditor";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";

interface WikiPageData {
  id: string;
  name: string;
  category: string;
  tags: string[];
  linked_service?: string;
  content: string;
  credentials: {
    key: string;
    label: string;
    value?: string;
    expires?: string;
    rotate_days?: number;
  }[];
  updated_at?: string;
}

interface Props {
  pageId: string;
  onBack: () => void;
  onEdit: (id: string) => void;
}

export function WikiPageView({ pageId, onBack, onEdit }: Props) {
  const { t } = useTranslation(["session", "common"]);
  const [page, setPage] = useState<WikiPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getWikiPage(pageId)
      .then((data: any) => setPage(data))
      .catch(() => setPage(null))
      .finally(() => setLoading(false));
  }, [pageId]);

  const handleDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await deleteWikiPage(pageId);
      onBack();
    } catch {
      // silently fail
    }
  };

  const handleSummarize = async () => {
    setSummaryLoading(true);
    try {
      const r = await fetch(`/v1/wiki/${pageId}/summarize`, { method: "POST" });
      const d = await r.json();
      if (d.ok) setSummary(d.summary);
    } catch { /* ignore */ }
    setSummaryLoading(false);
  };

  if (loading) {
    return (
      <div className="p-6 text-center text-muted text-[13px]">{t("common:status.loading")}</div>
    );
  }

  if (!page) {
    return (
      <div className="p-6 text-center text-muted text-[13px]">
        {t("common:error.pageNotFound")}
        <button
          className="ml-2 text-accent hover:underline"
          onClick={onBack}
        >
          {t("session:wiki.cancel")}
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* Back */}
      <button
        className="flex items-center gap-1.5 text-[12.5px] text-muted hover:text-ink"
        onClick={onBack}
      >
        <Icon name="arrowLeft" size={14} />
        {t("session:wiki.title")}
      </button>

      {/* Header */}
      <div className={CARD + " p-4"}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[18px] font-semibold tracking-tight truncate">
              {page.name}
            </h2>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {page.category && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-accentSoft text-accent font-medium">
                  {page.category}
                </span>
              )}
              {page.tags?.map((tag) => (
                <span
                  key={tag}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-faint/20 text-muted"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              className="text-[12.5px] px-3 py-1.5 rounded-lg border border-line text-muted hover:text-ink hover:bg-paper flex items-center gap-1.5"
              onClick={() => onEdit(pageId)}
            >
              <Icon name="pencil" size={13} />
              {t("session:wiki.edit")}
            </button>
            <button
              className={
                "text-[12.5px] px-3 py-1.5 rounded-lg border border-line flex items-center gap-1.5 " +
                (confirmDelete
                  ? "text-danger border-danger font-medium"
                  : "text-muted hover:text-danger hover:bg-paper")
              }
              onClick={handleDelete}
            >
              <Icon name="trash" size={13} />
              {confirmDelete
                ? t("session:wiki.deleteConfirm")
                : t("session:wiki.delete")}
            </button>
          </div>
        </div>
      </div>

      {/* Credentials */}
      {page.credentials && page.credentials.length > 0 && (
        <WikiCredentialCard pageId={pageId} credentials={page.credentials} />
      )}

      {/* AI Summary */}
      <div className="flex items-center gap-2">
        <button
          className="text-[12.5px] px-3 py-1.5 rounded-lg border border-line text-muted hover:text-ink flex items-center gap-1.5"
          onClick={handleSummarize}
          disabled={summaryLoading}
        >
          <Icon name="sparkle" size={13} />
          {summaryLoading
            ? t("common:status.loading")
            : t("session:wiki.aiSummary")}
        </button>
      </div>

      {summary && (
        <div className={CARD + " p-4"}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-[13px] font-semibold text-ink">{t("session:wiki.aiSummary")}</h3>
            <button
              className="text-[11px] text-muted hover:text-ink"
              onClick={() => setSummary(null)}
            >
              {t("session:wiki.cancel")}
            </button>
          </div>
          <pre className="text-[12px] text-ink whitespace-pre-wrap">{summary}</pre>
        </div>
      )}

      {/* Content */}
      {page.content && (
        <div className={CARD + " p-4"}>
          <Markdown text={page.content} />
        </div>
      )}

      {/* Prompt editor for prompt-category pages */}
      {page.category === "prompt" && (
        <WikiPromptEditor pageId={pageId} content={page.content} />
      )}

      {/* Action buttons based on linked service */}
      {page.linked_service && (
        <div className="flex items-center gap-2">
          {page.linked_service.startsWith("database:") && (
            <button className="text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white flex items-center gap-1.5">
              <Icon name="table" size={13} />
              {t("session:wiki.connect")}
            </button>
          )}
          {page.linked_service.startsWith("ssh:") && (
            <>
              <button className="text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white flex items-center gap-1.5">
                <Icon name="wrench" size={13} />
                {t("session:wiki.checkStatus")}
              </button>
              <button className="text-[12.5px] px-3 py-2 rounded-lg border border-line text-muted hover:text-ink flex items-center gap-1.5">
                {t("session:wiki.backup")}
              </button>
            </>
          )}
          {page.linked_service.startsWith("aws:") && (
            <button className="text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white flex items-center gap-1.5">
              {t("session:wiki.checkStatus")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
