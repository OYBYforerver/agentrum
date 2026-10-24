"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface Stats {
  resources_by_kind: Record<string, number>;
  total_resources: number;
  published_last_7d: number;
  subscribers: number;
  pending_approvals: number;
}

const KIND_ORDER = ["MCPServer", "Agent", "Skill", "Prompt"];

export default function Overview({
  project,
  onOpen,
}: {
  project: string;
  onOpen: (tab: "MCP Servers" | "Agents" | "Skills" | "Prompts" | "subscriptions") => void;
}) {
  const { t } = useTranslation();
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<Stats>(`/v1/teams/${project}/stats`)
      .then(setStats)
      .catch((e) => setError(String(e).replace("Error: ", "")));
  }, [project]);

  if (error) return <p className="error">{error}</p>;
  if (!stats) return <p className="muted">…</p>;

  return (
    <div>
      <div className="stats">
        <div className="card stat">
          <div className="num">{stats.total_resources}</div>
          <div className="label">{t("overview.total")}</div>
        </div>
        <div className="card stat">
          <div className="num">{stats.published_last_7d}</div>
          <div className="label">{t("overview.week")}</div>
        </div>
        <div className="card stat">
          <div className="num">{stats.subscribers}</div>
          <div className="label">{t("overview.subscribers")}</div>
        </div>
        <div className="card stat" style={stats.pending_approvals ? { borderColor: "var(--warn)" } : undefined}>
          <div className="num">{stats.pending_approvals}</div>
          <div className="label">{t("overview.pending")}</div>
        </div>
      </div>

      <div className="proj-grid">
        {KIND_ORDER.map((k) => (
          <div
            key={k}
            className="card proj-card"
            onClick={() =>
              onOpen(
                k === "MCPServer"
                  ? "MCP Servers"
                  : k === "Agent"
                    ? "Agents"
                    : k === "Skill"
                      ? "Skills"
                      : "Prompts"
              )
            }
          >
            <h3 style={{ margin: "0 0 6px" }}>
              {t(`nav.kinds.${{ MCPServer: "mcp", Agent: "agents", Skill: "skills", Prompt: "prompts" }[k]}`)}
            </h3>
            <div className="num" style={{ fontSize: 22, fontWeight: 700 }}>
              {stats.resources_by_kind[k] || 0}
            </div>
          </div>
        ))}
        <div className="card proj-card" onClick={() => onOpen("subscriptions")}>
          <h3 style={{ margin: "0 0 6px" }}>{t("subs.mine")}</h3>
          <div className="muted" style={{ fontSize: 13 }}>{t("overview.subsHint")}</div>
        </div>
      </div>
    </div>
  );
}
