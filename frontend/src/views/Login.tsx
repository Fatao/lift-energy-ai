import { useState } from "react";
import { api } from "../api";
import { useI18n } from "../i18n";

export default function Login({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [user, setUser] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await api.login(user.trim(), password);
      onDone();
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <svg viewBox="0 0 32 32" className="mark big" aria-hidden="true"><rect width="32" height="32" rx="8" /><path d="M18 4 8 18h7l-1 10 10-14h-7z" /></svg>
        <h1>{t("app.name")}</h1>
        <p className="muted">{t("login.sub")}</p>
        <label>{t("login.user")}
          <input value={user} autoComplete="username" onChange={(e) => setUser(e.target.value)} />
        </label>
        <label>{t("login.password")}
          <input type="password" value={password} autoFocus autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        {err && <div className="login-err" role="alert">{err}</div>}
        <button className="btn" type="submit" disabled={busy || !password}>
          {busy ? t("login.busy") : t("login.submit")}
        </button>
      </form>
    </div>
  );
}