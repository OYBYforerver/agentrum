"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Boxes, Link2, LockKeyhole, Rocket, Server, ShieldCheck,
} from "lucide-react";
import { api, setServer, setToken } from "../lib/api";
import { setLocale } from "../lib/i18n";

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

  const features = [
    { icon: Boxes, key: "f1" },
    { icon: Link2, key: "f2" },
    { icon: ShieldCheck, key: "f3" },
    { icon: Rocket, key: "f4" },
  ];

  return (
    <main className="login-shell">
      {/* 品牌视觉面板 */}
      <section className="login-brand">
        <div className="brand-glow g1" />
        <div className="brand-glow g2" />
        <div className="brand-grid" />
        <div className="brand-inner">
          <div className="brand-logo">
            <span className="dot" /> Agentrum
          </div>
          <h1 className="brand-title">
            {t("login.heroTitle")}
            <br />
            <span className="brand-gradient-text">{t("login.heroAccent")}</span>
          </h1>
          <p className="brand-sub">{t("login.heroSub")}</p>

          <ul className="brand-features">
            {features.map(({ icon: Icon, key }) => (
              <li key={key}>
                <span className="feat-icon">
                  <Icon size={15} />
                </span>
                {t(`login.${key}`)}
              </li>
            ))}
          </ul>

          {/* 迷你控制台模型 */}
          <div className="brand-mock">
            <div className="mock-head">
              <span className="mdot" /><span className="mdot" /><span className="mdot" />
              <span className="mock-title">payment · 概览</span>
            </div>
            <div className="mock-stats">
              <div><b>8</b><span>{t("login.mockRes")}</span></div>
              <div><b>9</b><span>{t("login.mockPub")}</span></div>
              <div><b>3</b><span>{t("login.mockSub")}</span></div>
            </div>
            <div className="mock-row"><Server size={12} /> payment-gateway <span className="mock-badge">v1.3.0</span></div>
            <div className="mock-row"><Boxes size={12} /> fraud-detection <span className="mock-badge warn">restricted</span></div>
          </div>

          <p className="brand-foot">{t("login.heroFoot")}</p>
        </div>
      </section>

      {/* 表单面板 */}
      <section className="login-form-side">
        <div className="login-card">
          <h1 style={{ margin: 0, fontSize: 24 }}>
            <span className="dot" style={{ display: "inline-block", width: 11, height: 11, borderRadius: 4, background: "linear-gradient(135deg,#4f46e5,#06b6d4)", marginRight: 8 }} />
            Agentrum
          </h1>
          <p style={{ color: "var(--muted)", marginTop: 6, fontSize: 13 }}>{t("login.heading")}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
            style={{ display: "grid", gap: 12, marginTop: 22 }}
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
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
            <span style={{ color: "var(--muted)", fontSize: 13 }}>{t("login.orSso")}</span>
            <select
              value={(i18n.language || "zh").startsWith("zh") ? "zh" : "en"}
              onChange={(e) => setLocale(e.target.value as "zh" | "en")}
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </section>
    </main>
  );
}
