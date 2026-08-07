import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { revealWikiCredential } from "../api";
import { Icon } from "./Icon";

interface Credential {
  key: string;
  label: string;
  value?: string;
  expires?: string;
  rotate_days?: number;
}

interface Props {
  pageId: string;
  credentials: Credential[];
}

export function WikiCredentialCard({ pageId, credentials }: Props) {
  const { t } = useTranslation(["session"]);

  if (!credentials || credentials.length === 0) return null;

  return (
    <div className="rounded-xl2 border border-line bg-panel p-4 space-y-3">
      <h3 className="text-[13px] font-semibold">{t("session:wiki.credentials")}</h3>
      <div className="space-y-2">
        {credentials.map((cred) => (
          <CredentialRow key={cred.key} pageId={pageId} credential={cred} />
        ))}
      </div>
    </div>
  );
}

function CredentialRow({
  pageId,
  credential,
}: {
  pageId: string;
  credential: Credential;
}) {
  const { t } = useTranslation(["session"]);
  const [revealed, setRevealed] = useState(false);
  const [revealedValue, setRevealedValue] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const daysUntilExpiry = useCallback(() => {
    if (!credential.expires) return null;
    const diff = Date.parse(credential.expires) - Date.now();
    return Math.ceil(diff / (1000 * 60 * 60 * 24));
  }, [credential.expires]);

  const expiryDays = daysUntilExpiry();

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleReveal = async () => {
    if (revealed) {
      setRevealed(false);
      setRevealedValue(null);
      if (timerRef.current) clearTimeout(timerRef.current);
      return;
    }
    try {
      const res = await revealWikiCredential(pageId, credential.key);
      setRevealedValue(res.value);
      setRevealed(true);
      timerRef.current = setTimeout(() => {
        setRevealed(false);
        setRevealedValue(null);
      }, 5000);
    } catch {
      // silently fail
    }
  };

  const handleCopy = async () => {
    try {
      const res = await revealWikiCredential(pageId, credential.key);
      await navigator.clipboard.writeText(res.value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // silently fail
    }
  };

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-paper/60">
      <div className="flex-1 min-w-0">
        <div className="text-[12.5px] font-medium text-ink truncate">
          {credential.label || credential.key}
        </div>
        <div className="text-[12px] text-muted font-mono truncate">
          {revealed && revealedValue ? revealedValue : "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"}
        </div>
      </div>

      {expiryDays !== null && (
        <span
          className={
            "text-[11px] px-2 py-0.5 rounded-full shrink-0 " +
            (expiryDays <= 0
              ? "bg-danger/10 text-danger font-semibold"
              : expiryDays <= 14
                ? "bg-warn/10 text-warn font-semibold"
                : "bg-faint/20 text-muted")
          }
        >
          {expiryDays <= 0
            ? t("session:wiki.expired")
            : t("session:wiki.daysLeft", { days: expiryDays })}
        </span>
      )}

      {credential.rotate_days && expiryDays !== null && expiryDays <= (credential.rotate_days || 0) && (
        <span className="text-[11px] text-warn shrink-0">
          {t("session:wiki.rotationDue")}
        </span>
      )}

      <button
        className="text-[12px] px-2 py-1 rounded-md text-muted hover:text-ink hover:bg-paper shrink-0 flex items-center gap-1"
        onClick={handleCopy}
        title={t("session:wiki.copy")}
      >
        <Icon name="copy" size={13} />
        {copied ? t("session:wiki.copied") : t("session:wiki.copy")}
      </button>

      <button
        className="text-[12px] px-2 py-1 rounded-md text-muted hover:text-ink hover:bg-paper shrink-0 flex items-center gap-1"
        onClick={handleReveal}
        title={revealed ? t("session:wiki.hide") : t("session:wiki.show")}
      >
        <Icon name={revealed ? "x" : "search"} size={13} />
        {revealed ? t("session:wiki.hide") : t("session:wiki.show")}
      </button>
    </div>
  );
}
