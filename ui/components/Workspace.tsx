"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen, Bot, Boxes, FileText, Home, Link2, LogOut, Moon, Plug, Search, Server, Settings as SettingsIcon, ShieldCheck, Zap,
} from "lucide-react";
import { api, errMsg, getServer } from "../lib/api";
import { setLocale } from "../lib/i18n";
import { toggleTheme } from "../lib/theme";
import Grants from "./Grants";
import Overview from "./Overview";
import ProjectsInline from "./ProjectsInline";
import ResourceTab from "./ResourceTab";
import Settings from "./Settings";
import Subscriptions from "./Subscriptions";

type View =
  | { tab: "overview" }
  | { tab: "projects" }
  | { tab: "MCP Servers" }
  | { tab: "Agents" }
  | { tab: "Skills" }
  | { tab: "Prompts" }
  | { tab: "subscriptions" }
  | { tab: "grants" }
  | { tab: "settings" };

const RESOURCE_TABS: {
  id: "MCP Servers" | "Agents" | "Skills" | "Prompts";
  icon: typeof Server;
  kindKey: "mcp" | "agents" | "skills" | "prompts";
}[] = [
  { id: "MCP Servers", icon: Server, kindKey: "mcp" },
  { id: "Agents", icon: Bot, kindKey: "agents" },
  { id: "Skills", icon: Zap, kindKey: "skills" },
  { id: "Prompts", icon: FileText, kindKey: "prompts" },
];

export default function Workspace({
  project,
  onSwitch,
  onExit,
}: {
  project: string;
  onSwitch: (p: string) => void;
  onExit: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<View>({ tab: "overview" });
  const [allProjects, setAllProjects] = useState<string[]>([project]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{
    projects: string[];
    resources: { ref: string; kind: string; namespace: string; name: string }[];
  }>({ projects: [], resources: [] });
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api<{ name: string }[]>("/v1/teams")
      .then((ts) => setAllProjects(ts.map((x) => x.name)))
      .catch(() => {});
  }, []);

  // 顶栏快速搜索:项目 + 全局资源,300ms 防抖
  useEffect(() => {
    if (!searchOpen || !query.trim()) return;
    const handle = setTimeout(async () => {
      try {
        const res = await api<{ items: { kind: string; namespace: string; name: string }[] }>(
          `/v1/resources?q=${encodeURIComponent(query)}&limit=8`
        );
        setResults({
          projects: allProjects.filter((p) => p.toLowerCase().includes(query.toLowerCase())),
          resources: res.items.map((r) => ({ ...r, ref: `${r.kind}/${r.namespace}/${r.name}` })),
        });
      } catch {
        /* ignore */
      }
    }, 300);
    return () => clearTimeout(handle);
  }, [query, searchOpen, allProjects]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setSearchOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const kindOf =
    view.tab === "MCP Servers"
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
          <img src="/icon.svg" alt="" width={20} height={20} style={{ borderRadius: 5 }} /> Agentrum
        </div>
        <select value={project} onChange={(e) => onSwitch(e.target.value)} title={t("projects.switcher")}>
          {allProjects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button
          className={`nav-item ${view.tab === "projects" ? "active" : ""}`}
          onClick={() => setView({ tab: "projects" })}
          style={{ marginBottom: 8 }}
        >
          <Home size={15} /> {t("nav.myProjects")}
        </button>
        <button
          className={`nav-item ${view.tab === "overview" ? "active" : ""}`}
          onClick={() => setView({ tab: "overview" })}
        >
          <Boxes size={15} /> {t("overview.nav")}
        </button>
        {RESOURCE_TABS.map((rt) => {
          const Icon = rt.icon;
          return (
            <button
              key={rt.id}
              className={`nav-item ${view.tab === rt.id ? "active" : ""}`}
              onClick={() => setView({ tab: rt.id } as View)}
            >
              <Icon size={15} /> {t(`nav.kinds.${rt.kindKey}`)}
            </button>
          );
        })}
        <button
          className={`nav-item ${view.tab === "subscriptions" ? "active" : ""}`}
          onClick={() => setView({ tab: "subscriptions" })}
        >
          <Link2 size={15} /> {t("nav.subscriptions")}
        </button>
        <button
          className={`nav-item ${view.tab === "grants" ? "active" : ""}`}
          onClick={() => setView({ tab: "grants" })}
        >
          <ShieldCheck size={15} /> {t("nav.grants")}
        </button>
        <button
          className={`nav-item ${view.tab === "settings" ? "active" : ""}`}
          onClick={() => setView({ tab: "settings" })}
        >
          <SettingsIcon size={15} /> {t("nav.settings")}
        </button>
        <div className="spacer" />
        <div className="userbox">
          <a className="nav-item" href={`${getServer()}/handbook/`} target="_blank" rel="noreferrer">
            <BookOpen size={15} /> {t("nav.docs")}
          </a>
          <a className="nav-item" href={`${getServer()}/docs`} target="_blank" rel="noreferrer">
            <Plug size={15} /> {t("nav.apiDocs")}
          </a>
          <select
            value={(i18n.language || "zh").startsWith("zh") ? "zh" : "en"}
            onChange={(e) => setLocale(e.target.value as "zh" | "en")}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
          <button className="nav-item" onClick={() => toggleTheme()}>
            <Moon size={15} /> {t("nav.theme")}
          </button>
          <button className="nav-item" onClick={() => void logout()}>
            <LogOut size={15} /> {t("nav.logout")}
          </button>
        </div>
      </aside>
      <main className="content">
        <div className="topbar">
          <div className="crumbs">
            <span
              className={view.tab === "projects" ? "crumb-active" : "crumb-link"}
              onClick={() => setView({ tab: "projects" })}
            >
              {t("nav.myProjects")}
            </span>
            {view.tab !== "projects" && (
              <>
                <span className="muted"> / </span>
                <span className="crumb-active">{project}</span>
              </>
            )}
          </div>
          <div className="searchbox" ref={searchRef}>
            <Search size={14} style={{ position: "absolute", left: 10, top: 9, color: "var(--muted)" }} />
            <input
              value={query}
              placeholder={t("search.placeholder")}
              onFocus={() => setSearchOpen(true)}
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchOpen(true);
              }}
            />
            {searchOpen && query.trim() && (
              <div className="combo-list" style={{ left: 0, right: 0 }}>
                {results.projects.map((p) => (
                  <div
                    key={p}
                    className="combo-item"
                    onMouseDown={() => {
                      onSwitch(p);
                      setSearchOpen(false);
                      setQuery("");
                    }}
                  >
                    <strong>{p}</strong>
                  </div>
                ))}
                {results.resources.map((r) => (
                  <div
                    key={r.ref}
                    className="combo-item"
                    onMouseDown={() => {
                      const map: Record<string, string> = {
                        MCPServer: "MCP Servers",
                        Agent: "Agents",
                        Skill: "Skills",
                        Prompt: "Prompts",
                      };
                      if (r.namespace === project && map[r.kind]) {
                        setView({ tab: map[r.kind] } as View);
                      }
                      setSearchOpen(false);
                      setQuery("");
                    }}
                  >
                    <div>
                      <strong>{r.name}</strong>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {r.kind} · {r.namespace}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        {view.tab !== "projects" && (
        <h2 className="page">
          {view.tab === "overview"
            ? t("overview.nav")
            : view.tab === "subscriptions"
              ? t("subs.mine")
              : view.tab === "grants"
                ? t("nav.grants")
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
        )}
        {view.tab === "projects" ? (
          <ProjectsInline
            projects={allProjects}
            current={project}
            onPick={(p) => {
              onSwitch(p);
              setView({ tab: "overview" });
            }}
          />
        ) : view.tab === "overview" ? (
          <Overview project={project} onOpen={(tab) => setView({ tab } as View)} />
        ) : kindOf ? (
          <ResourceTab kind={kindOf} namespace={project} />
        ) : view.tab === "subscriptions" ? (
          <Subscriptions project={project} />
        ) : view.tab === "grants" ? (
          <Grants project={project} />
        ) : (
          <Settings project={project} />
        )}
      </main>
    </div>
  );
}
