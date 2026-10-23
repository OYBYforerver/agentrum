"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, setServer, setToken } from "../lib/api";

export default function Login({ onOk }: { onOk: () => void }) {
  const { t, i18n } = useTranslation();
  const [server, setSrv] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError("");
    setBusy(true);
    try {
      setServer(server);
      const data = await api<{ access_token: string }>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(data.access_token);
      onOk();
    } catch (e) {
      setError(t("login.error", { detail: String(e).replace("Error: ", "") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background:
          "radial-gradient(1200px 500px at 20% -10%, rgba(79,70,229,0.15), transparent), radial-gradient(1000px 500px at 90% 110%, rgba(6,182,212,0.12), transparent)",
      }}
    >
      <div className="card" style={{ width: 400, padding: 32 }}>
        <h1 style={{ margin: 0, textAlign: "center", fontSize: 26 }}>
          <span className="dot" style={{ display: "inline-block", width: 12, height: 12, borderRadius: 4, background: "linear-gradient(135deg,#4f46e5,#06b6d4)", marginRight: 8 }} />
          Agentrum
        </h1>
        <p style={{ textAlign: "center", color: "var(--muted)", marginTop: 6 }}>{t("app.tagline")}</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          style={{ display: "grid", gap: 12, marginTop: 20 }}
        >
          <label>{t("login.server")}</label>
          <input value={server} onChange={(e) => setSrv(e.target.value)} placeholder="http://localhost:12122" />
          <label>{t("login.username")}</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label>{t("login.password")}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <span className="error">{error}</span>}
          <button className="primary" disabled={busy}>
            {busy ? "…" : t("login.submit")}
          </button>
        </form>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 18 }}>
          <a href="#" style={{ color: "var(--muted)", fontSize: 13 }} onClick={(e) => e.preventDefault()}>
            {t("login.orSso")}
          </a>
          <select
            value={(i18n.language || "zh").startsWith("zh") ? "zh" : "en"}
            onChange={(e) => void i18n.changeLanguage(e.target.value)}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>
    </main>
  );
}
