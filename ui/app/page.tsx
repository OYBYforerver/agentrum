"use client";

import "../lib/i18n";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getToken } from "../lib/api";
import { applyTheme, getTheme } from "../lib/theme";
import Login from "../components/Login";
import Projects from "../components/Projects";
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
  if (!project) return <Projects onEnter={(p) => setProject(p)} />;
  return (
    <Workspace
      project={project}
      onSwitch={setProject}
      onBack={() => setProject(null)}
      onExit={() => {
        setProject(null);
        setAuthed(false);
      }}
    />
  );
}
