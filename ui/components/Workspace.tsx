"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { setLocale } from "../lib/i18n";
import { toggleTheme } from "../lib/theme";
import ResourceTab from "./ResourceTab";
import Settings from "./Settings";
import Subscriptions from "./Subscriptions";

type View =
  | { tab: "MCP Servers" }
  | { tab: "Agents" }
  | { tab: "Skills" }
  | { tab: "Prompts" }
  | { tab: "subscriptions" }
  | { tab: "settings" };

const RESOURCE_TABS: { id: "MCP Servers" | "Agents" | "Skills" | "Prompts"; icon: string; kindKey: "mcp" | "agents" | "skills" | "prompts" }[] = [
  { id: "MCP Servers", icon: "🖥", kindKey: "mcp" },
  { id: "Agents", icon: "🤖", kindKey: "agents" },
  { id: "Skills", icon: "⚡", kindKey: "skills" },
  { id: "Prompts", icon: "📝", kindKey: "prompts" },
];

export default function Workspace({
  project,
  onSwitch,
  onBack,
  onExit,
}: {
  project: string;
  onSwitch: (p: string) => void;
  onBack: () => void;
  onExit: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<View>({ tab: "MCP Servers" });
  const [allProjects, setAllProjects] = useState<string[]>([project]);

  useEffect(() => {
    void api<{ name: string }[]>("/v1/teams")
      .then((ts) => setAllProjects(ts.map((x) => x.name)))
      .catch(() => {});
  }, []);

  const kindOf = view.tab.startsWith("MCP")
    ? "MCPServer"
    : view.tab === "Agents"
      ? "Agent"
      : view.tab === "Skills"
        ? "Skill"
        : view.tab === "Prompts"
          ? "Prompt"
          : null;

  async function logout() {
    localStorage.removeItem("agentrum-token");
    onExit();
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <span className="dot" /> Agentrum
        </div>
        <select value={project} onChange={(e) => onSwitch(e.target.value)} title={t("projects.switcher")}>
          {allProjects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button className="nav-item" onClick={onBack} style={{ marginTop: 8 }}>
          <span>🏠</span> {t("nav.myProjects")}
        </button>
        <div style={{ height: 12 }} />
        {RESOURCE_TABS.map((rt) => (
          <button
            key={rt.id}
            className={`nav-item ${view.tab === rt.id ? "active" : ""}`}
            onClick={() => setView({ tab: rt.id } as View)}
          >
            <span>{rt.icon}</span> {t(`nav.kinds.${rt.kindKey}`)}
          </button>
        ))}
        <button
          className={`nav-item ${view.tab === "subscriptions" ? "active" : ""}`}
          onClick={() => setView({ tab: "subscriptions" })}
        >
          <span>🔗</span> {t("nav.subscriptions")}
        </button>
        <button
          className={`nav-item ${view.tab === "settings" ? "active" : ""}`}
          onClick={() => setView({ tab: "settings" })}
        >
          <span>⚙</span> {t("nav.settings")}
        </button>
        <div className="spacer" />
        <div className="userbox">
          <select
            value={(i18n.language || "zh").startsWith("zh") ? "zh" : "en"}
            onChange={(e) => setLocale(e.target.value as "zh" | "en")}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
          <button className="nav-item" onClick={() => toggleTheme()}>
            🌓 {t("nav.theme")}
          </button>
          <button className="nav-item" onClick={() => void logout()}>
            ⎋ {t("nav.logout")}
          </button>
        </div>
      </aside>
      <main className="content">
        <div className="crumbs">
          <button className="crumb-link" onClick={onBack}>
            {t("nav.myProjects")}
          </button>
          <span className="muted"> / </span>
          <span>{project}</span>
        </div>
        <h2 className="page">
          {view.tab === "subscriptions"
            ? t("subs.mine")
            : view.tab === "settings"
              ? t("nav.settings")
              : RESOURCE_TABS.find((rt) => rt.id === view.tab)?.kindKey
                ? t(`nav.kinds.${RESOURCE_TABS.find((rt) => rt.id === view.tab)?.kindKey}`)
                : String(view.tab)}
          {kindOf && (
            <span className="muted" style={{ fontSize: 13, marginLeft: 10, fontWeight: 400 }}>
              {kindOf}
            </span>
          )}
        </h2>
        {kindOf ? (
          <ResourceTab kind={kindOf} namespace={project} />
        ) : view.tab === "subscriptions" ? (
          <Subscriptions project={project} />
        ) : (
          <Settings project={project} />
        )}
      </main>
    </div>
  );
}
