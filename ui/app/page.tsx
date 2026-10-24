"use client";

import "../lib/i18n";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getToken } from "../lib/api";
import { applyTheme, getTheme, toggleTheme } from "../lib/theme";
import { LogOut, Moon } from "lucide-react";
import Login from "../components/Login";
import ProjectsInline from "../components/ProjectsInline";
import Workspace from "../components/Workspace";

export default function Home() {
  const { t } = useTranslation();
  const [authed, setAuthed] = useState(false);
  const [project, setProject] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    applyTheme(getTheme());
    // OIDC callback: the backend redirects to {ui_origin}/#token=<JWT>&login=<username>.
    // The fragment never reaches the server; legacy ?token=/?login= query params still work.
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const url = new URL(window.location.href);
    const urlToken = hash.get("token") || url.searchParams.get("token");
    const urlLogin = hash.get("login") || url.searchParams.get("login");
    if (urlToken) {
      localStorage.setItem("agentrum-token", urlToken);
      if (urlLogin) localStorage.setItem("agentrum-login", urlLogin);
      // Strip the credential from the address bar but keep unrelated params (e.g. ?server=).
      url.hash = "";
      url.searchParams.delete("token");
      url.searchParams.delete("login");
      window.history.replaceState({}, "", url.pathname + url.search);
    }
    if (getToken()) setAuthed(true);
    setReady(true);
  }, []);

  if (!ready) return null;
  if (!authed) return <Login onOk={() => setAuthed(true)} />;
  if (!project)
    return (
      <main className="content" style={{ margin: "0 auto", minHeight: "100vh" }}>
        <header style={{ display: "flex", alignItems: "center", gap: 10, padding: "18px 0 8px" }}>
          <img src="/icon.svg" alt="" width={20} height={20} style={{ borderRadius: 5 }} />
          <strong style={{ fontSize: 16 }}>Agentrum</strong>
          <span style={{ flex: 1 }} />
          <button
            className="ghost icon-btn"
            title={t("nav.theme")}
            onClick={() => toggleTheme()}
          >
            <Moon size={15} />
          </button>
          <button
            className="ghost icon-btn"
            title={t("nav.logout")}
            onClick={() => {
              localStorage.removeItem("agentrum-token");
              setAuthed(false);
            }}
          >
            <LogOut size={15} />
          </button>
        </header>
        <ProjectsInline onPick={(p) => setProject(p)} />
      </main>
    );
  return (
    <Workspace
      project={project}
      onSwitch={setProject}
      onExit={() => {
        setProject(null);
        setAuthed(false);
      }}
    />
  );
}
