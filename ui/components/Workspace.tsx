"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen, Boxes, FolderOpen, Home, Link2, LogOut, Moon, Plug, Search, Settings as SettingsIcon, ShieldCheck, ScrollText,
} from "lucide-react";
import { api, errMsg, getServer } from "../lib/api";
import { setLocale } from "../lib/i18n";
import { toggleTheme } from "../lib/theme";
import Audit from "./Audit";
import Catalog, { type CatalogKind } from "./Catalog";
import Grants from "./Grants";
import Overview from "./Overview";
import ProjectsInline from "./ProjectsInline";
import Settings from "./Settings";
import Subscriptions from "./Subscriptions";

type View =
  | { tab: "projects" }
  | { tab: "overview" }
  | { tab: "catalog"; kind: CatalogKind }
  | { tab: "subscriptions" }
  | { tab: "grants" }
  | { tab: "audit" }
  | { tab: "settings" };

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
  const [isAdmin, setIsAdmin] = useState(false);
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

  useEffect(() => {
    void api<{ is_platform_admin: boolean }>("/v1/auth/me")
      .then((me) => setIsAdmin(Boolean(me?.is_platform_admin)))
      .catch(() => setIsAdmin(false));
  }, []);

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
        <div className="nav-section">{t("nav.group.project")}</div>
        <button
          className={`nav-item ${view.tab === "overview" ? "active" : ""}`}
          onClick={() => setView({ tab: "overview" })}
        >
          <Boxes size={15} /> {t("overview.nav")}
        </button>
        <button
          className={`nav-item ${view.tab === "catalog" ? "active" : ""}`}
          onClick={() => setView({ tab: "catalog", kind: "MCPServer" })}
        >
          <FolderOpen size={15} /> {t("nav.catalog")}
        </button>
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
        {isAdmin && (
          <>
            <div className="nav-section">{t("nav.group.platform")}</div>
            <button
              className={`nav-item ${view.tab === "audit" ? "active" : ""}`}
              onClick={() => setView({ tab: "audit" })}
            >
              <ScrollText size={15} /> {t("nav.audit")}
            </button>
          </>
        )}
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
                      const kinds = ["MCPServer", "Agent", "Skill", "Prompt"];
                      if (r.namespace === project && kinds.includes(r.kind)) {
                        setView({ tab: "catalog", kind: r.kind as CatalogKind });
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
            : view.tab === "catalog"
              ? t("nav.catalog")
              : view.tab === "subscriptions"
                ? t("subs.mine")
                : view.tab === "grants"
                  ? t("nav.grants")
                  : view.tab === "settings"
                    ? t("nav.settings")
                    : String(view.tab)}
          {view.tab === "catalog" && (
            <span className="muted" style={{ fontSize: 13, marginLeft: 10, fontWeight: 400 }}>
              {view.kind}
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
          <Overview
            project={project}
            onOpen={(tab, kind) =>
              setView(tab === "catalog" ? { tab: "catalog", kind: kind ?? "MCPServer" } : { tab })
            }
          />
        ) : view.tab === "catalog" ? (
          <Catalog
            project={project}
            kind={view.kind}
            onKind={(kind) => setView({ tab: "catalog", kind })}
          />
        ) : view.tab === "subscriptions" ? (
          <Subscriptions project={project} />
        ) : view.tab === "grants" ? (
          <Grants project={project} />
        ) : view.tab === "audit" ? (
          <Audit />
        ) : (
          <Settings project={project} />
        )}
      </main>
    </div>
  );
}
