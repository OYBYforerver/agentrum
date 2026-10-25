"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, errMsg } from "../lib/api";

interface ActivityRow {
  action: string;
  actor: string | null;
  kind: string | null;
  namespace: string | null;
  name: string | null;
  occurred_at: string;
}

interface Stats {
  resources_by_kind: Record<string, number>;
  total_resources: number;
  published_last_7d: number;
  subscribers: number;
  pending_approvals: number;
}

const KIND_ORDER: ("MCPServer" | "Agent" | "Skill" | "Prompt")[] = ["MCPServer", "Agent", "Skill", "Prompt"];

export default function Overview({
  project,
  onOpen,
}: {
  project: string;
  onOpen: (
    tab: "catalog" | "subscriptions",
    kind?: "MCPServer" | "Agent" | "Skill" | "Prompt"
  ) => void;
}) {
  const { t } = useTranslation();
  const [stats, setStats] = useState<Stats | null>(null);
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<Stats>(`/v1/teams/${project}/stats`)
      .then(setStats)
      .catch((e) => setError(errMsg(e)));
    void api<ActivityRow[]>(`/v1/teams/${project}/activity`)
      .then(setActivity)
      .catch(() => {});
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

      {activity.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 20 }}>
          <table>
            <tbody>
              {activity.slice(0, 6).map((a, i) => (
                <tr key={i}>
                  <td style={{ width: 26 }}>
                    <span className={`dot-ev ${a.action.includes("delete") || a.action.includes("reject") ? "bad" : "ok"}`} />
                  </td>
                  <td>
                    <strong>{a.actor || "-"}</strong> {t(`activity.${a.action}`, a.action)}
                    {a.name ? <strong> {a.kind} {a.name}</strong> : ""}
                    <span className="muted" style={{ fontSize: 12 }}> · {a.occurred_at.slice(5, 16).replace("T", " ")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="proj-grid">
        {KIND_ORDER.map((k) => (
          <div
            key={k}
            className="card proj-card"
            onClick={() => onOpen("catalog", k)}
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
