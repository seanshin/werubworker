import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

// The Persona Gallery modal — Cloud gallery is not available. Show a message
// directing users to install personas from a Git URL or local folder instead.

export function GalleryModal({
  onClose,
  onInstalled: _onInstalled,
}: {
  onClose: () => void;
  onInstalled?: () => void;
}) {
  const { t } = useTranslation(["settings", "common"]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50" data-testid="gallery-modal">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />
      <div className="absolute left-1/2 top-[6vh] -translate-x-1/2 w-[720px] max-w-[94vw] max-h-[88vh] rounded-xl2 border border-line bg-panel shadow-2xl overflow-hidden flex flex-col">
        <div className="px-5 pt-4 pb-3 border-b border-line flex items-center gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold">{t("settings:gallery.title")}</div>
            <div className="text-[12px] text-muted">
              {t("settings:gallery.subtitle")}
            </div>
          </div>
          <button
            className="text-faint hover:text-ink shrink-0"
            onClick={onClose}
            aria-label={t("settings:gallery.closeGallery")}
            data-testid="gallery-close"
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="overflow-y-auto hairline-scroll p-5">
          <div className="rounded-xl border border-line bg-panel/60 p-5 text-center space-y-3">
            <div className="text-[14px] font-semibold">
              Gallery is not available
            </div>
            <div className="text-[13px] text-muted leading-relaxed max-w-md mx-auto">
              The cloud-hosted persona gallery is not configured. You can install
              personas from a Git URL or a local folder on the Personas settings page.
            </div>
            <button
              className="text-[12.5px] px-4 py-2 rounded-lg border border-line text-muted hover:text-ink hover:border-lineStrong"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
