import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getWikiPage,
  getWikiCategories,
  createWikiPage,
  updateWikiPage,
} from "../api";
import { Icon } from "./Icon";

const CARD = "rounded-xl2 border border-line bg-panel";
const BTN_ACCENT =
  "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";

interface CredentialEntry {
  key: string;
  label: string;
  value: string;
  expires: string;
  rotate_days: number | "";
}

interface Props {
  pageId?: string | null;
  onSave: () => void;
  onCancel: () => void;
}

export function WikiPageEditor({ pageId, onSave, onCancel }: Props) {
  const { t } = useTranslation(["session", "common"]);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [linkedService, setLinkedService] = useState("");
  const [content, setContent] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [credentials, setCredentials] = useState<CredentialEntry[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getWikiCategories()
      .then((cats: any) => {
        if (Array.isArray(cats)) setCategories(cats);
        else if (cats?.categories) setCategories(cats.categories);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!pageId) return;
    getWikiPage(pageId)
      .then((page: any) => {
        setName(page.name || "");
        setCategory(page.category || "");
        setTags((page.tags || []).join(", "));
        setLinkedService(page.linked_service || "");
        setContent(page.content || "");
        setCredentials(
          (page.credentials || []).map((c: any) => ({
            key: c.key || "",
            label: c.label || "",
            value: "",
            expires: c.expires || "",
            rotate_days: c.rotate_days ?? "",
          })),
        );
      })
      .catch(() => {});
  }, [pageId]);

  const addCredential = () => {
    setCredentials((prev) => [
      ...prev,
      { key: "", label: "", value: "", expires: "", rotate_days: "" },
    ]);
  };

  const updateCredential = (
    index: number,
    field: keyof CredentialEntry,
    value: string | number,
  ) => {
    setCredentials((prev) =>
      prev.map((c, i) => (i === index ? { ...c, [field]: value } : c)),
    );
  };

  const removeCredential = (index: number) => {
    setCredentials((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    const data = {
      name: name.trim(),
      category,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      linked_service: linkedService || null,
      content,
      change_note: changeNote || undefined,
      credentials: credentials
        .filter((c) => c.key.trim())
        .map((c) => ({
          key: c.key.trim(),
          label: c.label.trim(),
          value: c.value || undefined,
          expires: c.expires || undefined,
          rotate_days: c.rotate_days ? Number(c.rotate_days) : undefined,
        })),
    };
    try {
      if (pageId) {
        await updateWikiPage(pageId, data);
      } else {
        await createWikiPage(data);
      }
      onSave();
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* Name */}
      <div>
        <label className="block text-[12.5px] font-medium mb-1">
          {t("session:wiki.name")}
        </label>
        <input
          className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("session:wiki.name")}
        />
      </div>

      {/* Category */}
      <div>
        <label className="block text-[12.5px] font-medium mb-1">
          {t("session:wiki.category")}
        </label>
        <select
          className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">--</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>

      {/* Tags */}
      <div>
        <label className="block text-[12.5px] font-medium mb-1">
          {t("session:wiki.tags")}
        </label>
        <input
          className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="tag1, tag2, ..."
        />
      </div>

      {/* Linked Service */}
      <div>
        <label className="block text-[12.5px] font-medium mb-1">
          {t("session:wiki.linkedService")}
        </label>
        <input
          className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
          value={linkedService}
          onChange={(e) => setLinkedService(e.target.value)}
          placeholder="database:*, ssh:server:*, aws:*, ..."
        />
      </div>

      {/* Credentials */}
      <div className={CARD + " p-4 space-y-3"}>
        <div className="flex items-center justify-between">
          <h3 className="text-[13px] font-semibold">
            {t("session:wiki.credentials")}
          </h3>
          <button
            className="text-[12.5px] text-accent font-medium hover:underline"
            onClick={addCredential}
          >
            {t("session:wiki.addCredential")}
          </button>
        </div>
        {credentials.map((cred, i) => (
          <div key={i} className="p-3 rounded-lg bg-paper/60 space-y-2">
            <div className="flex items-center gap-2">
              <input
                className="flex-1 px-2 py-1.5 rounded-md border border-line bg-panel text-[12.5px] outline-none"
                value={cred.key}
                onChange={(e) => updateCredential(i, "key", e.target.value)}
                placeholder={t("session:wiki.key")}
              />
              <input
                className="flex-1 px-2 py-1.5 rounded-md border border-line bg-panel text-[12.5px] outline-none"
                value={cred.label}
                onChange={(e) => updateCredential(i, "label", e.target.value)}
                placeholder={t("session:wiki.label")}
              />
              <button
                className="w-6 h-6 grid place-items-center rounded text-faint hover:text-danger shrink-0"
                onClick={() => removeCredential(i)}
                title={t("session:wiki.delete")}
              >
                <Icon name="trash" size={13} />
              </button>
            </div>
            <input
              type="password"
              className="w-full px-2 py-1.5 rounded-md border border-line bg-panel text-[12.5px] outline-none"
              value={cred.value}
              onChange={(e) => updateCredential(i, "value", e.target.value)}
              placeholder={t("session:wiki.secret")}
            />
            <div className="flex items-center gap-2">
              <input
                type="date"
                className="flex-1 px-2 py-1.5 rounded-md border border-line bg-panel text-[12.5px] outline-none"
                value={cred.expires}
                onChange={(e) => updateCredential(i, "expires", e.target.value)}
                title={t("session:wiki.expiresDate")}
              />
              <input
                type="number"
                className="w-32 px-2 py-1.5 rounded-md border border-line bg-panel text-[12.5px] outline-none"
                value={cred.rotate_days}
                onChange={(e) =>
                  updateCredential(
                    i,
                    "rotate_days",
                    e.target.value ? Number(e.target.value) : "",
                  )
                }
                placeholder={t("session:wiki.rotateDays")}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Content */}
      <div>
        <label className="block text-[12.5px] font-medium mb-1">
          {t("session:wiki.content")}
        </label>
        <textarea
          className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent font-mono min-h-[200px] resize-y"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={t("common:misc.markdownContent")}
        />
      </div>

      {/* Change note (for edits) */}
      {pageId && (
        <div>
          <label className="block text-[12.5px] font-medium mb-1">
            {t("session:wiki.changeNote")}
          </label>
          <input
            className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-[13px] outline-none focus:border-accent"
            value={changeNote}
            onChange={(e) => setChangeNote(e.target.value)}
            placeholder={t("session:wiki.changeNote")}
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          className={BTN_ACCENT}
          onClick={handleSave}
          disabled={saving || !name.trim()}
        >
          {t("session:wiki.save")}
        </button>
        <button
          className="text-[12.5px] px-3 py-2 rounded-lg border border-line text-muted hover:text-ink shrink-0"
          onClick={onCancel}
        >
          {t("session:wiki.cancel")}
        </button>
      </div>
    </div>
  );
}
