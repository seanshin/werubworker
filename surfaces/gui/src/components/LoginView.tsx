import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";

/**
 * Full-screen login / initial setup gate.
 *
 * - Not configured: password + confirm + "Set password" + "Later".
 * - Configured & locked: password + "Unlock".
 */
export function LoginView() {
  const { t } = useTranslation("auth");
  const { configured, login, setup, skip } = useAuth();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!configured) {
      // Setup flow
      if (password.length < 4) {
        setError(t("passwordTooShort"));
        return;
      }
      if (password !== confirm) {
        setError(t("passwordMismatch"));
        return;
      }
      setBusy(true);
      const res = await setup(password).catch(() => ({
        ok: false,
        error: t("genericError"),
      }));
      setBusy(false);
      if (!res.ok) setError(res.error || t("genericError"));
    } else {
      // Login flow
      setBusy(true);
      const res = await login(password).catch(() => ({
        ok: false,
        error: t("genericError"),
      }));
      setBusy(false);
      if (!res.ok) setError(res.error || t("incorrectPassword"));
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-paper">
      <div className="w-full max-w-[340px] px-6">
        <h1 className="text-[18px] font-semibold text-ink mb-1">
          {configured ? t("loginTitle") : t("setupTitle")}
        </h1>
        <p className="text-[13px] text-muted mb-5">
          {configured ? t("loginDescription") : t("setupDescription")}
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="password"
            placeholder={t("password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-ink text-[13px] outline-none focus:border-accent"
          />

          {!configured && (
            <input
              type="password"
              placeholder={t("confirmPassword")}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-line bg-panel text-ink text-[13px] outline-none focus:border-accent"
            />
          )}

          {error && (
            <div className="text-[12px] text-red-500">{error}</div>
          )}

          <button
            type="submit"
            disabled={busy || !password}
            className="w-full py-2 rounded-lg bg-accent text-white text-[13px] font-medium disabled:opacity-50"
          >
            {configured ? t("loginButton") : t("setupButton")}
          </button>

          {!configured && (
            <button
              type="button"
              onClick={skip}
              className="w-full py-2 rounded-lg border border-line text-muted text-[13px] hover:text-ink"
            >
              {t("laterButton")}
            </button>
          )}
        </form>

        {configured && (
          <p className="text-[11px] text-faint mt-4">{t("forgotHint")}</p>
        )}
      </div>
    </div>
  );
}
