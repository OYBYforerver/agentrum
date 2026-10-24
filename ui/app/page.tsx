"use client";

import "../lib/i18n";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getToken } from "../lib/api";
import { applyTheme, getTheme } from "../lib/theme";
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
    const url = new URL(window.location.href);
    const urlToken = url.searchParams.get("token");
    if (urlToken) {
      localStorage.setItem("agentrum-token", urlToken);
      window.history.replaceState({}, "", "/");
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
          <span className="dot" style={{ width: 11, height: 11, borderRadius: 4, background: "linear-gradient(135deg,#4f46e5,#06b6d4)", display: "inline-block" }} />
          <strong style={{ fontSize: 16 }}>Agentrum</strong>
          <span style={{ flex: 1 }} />
          <button
            className="ghost icon-btn"
            title={t("nav.theme")}
            onClick={() => applyTheme(getTheme() === "light" ? "dark" : "light")}
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
