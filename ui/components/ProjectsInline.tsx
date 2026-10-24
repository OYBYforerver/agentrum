"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, Boxes, Plus, Rocket, Search, Users } from "lucide-react";
import { api } from "../lib/api";

interface TeamRow {
  name: string;
  display_name: string | null;
  description: string | null;
  my_role: string | null;
}

interface Stats {
  total_resources: number;
  published_last_7d: number;
  subscribers: number;
}

interface CardState {
  stats?: Stats;
  lastActivity?: string;
}

const AVATAR_GRADIENTS = [
  "linear-gradient(135deg,#4F46E5,#06B6D4)",
  "linear-gradient(135deg,#7C3AED,#EC4899)",
  "linear-gradient(135deg,#059669,#22D3EE)",
  "linear-gradient(135deg,#EA580C,#FBBF24)",
  "linear-gradient(135deg,#2563EB,#7C3AED)",
];

/** Project selection — the landing view after login AND the in-shell switcher.
 * Rich cards: gradient avatar, per-project stats, role badges, create (admin). */
export default function ProjectsInline({
  projects,
  current,
  onPick,
}: {
  /** optional allowlist of visible projects; omit to show all teams */
  projects?: string[];
  current?: string;
  onPick: (name: string) => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [me, setMe] = useState<{ is_platform_admin: boolean } | null>(null);
  const [meta, setMeta] = useState<Record<string, CardState>>({});
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [users, setUsers] = useState<{ username: string; display_name: string | null }[]>([]);
  const [ownerQuery, setOwnerQuery] = useState("");
  const [ownerVal, setOwnerVal] = useState("");

  async function load() {
    try {
      const teams = await api<TeamRow[]>("/v1/teams");
      setRows(teams);
      setMe(await api<{ is_platform_admin: boolean }>("/v1/auth/me"));
      if (me?.is_platform_admin || me === null) {
        void api<{ username: string; display_name: string | null }[]>("/v1/users")
          .then(setUsers)
          .catch(() => {});
      }
      for (const tm of teams) {
        try {
          const stats = await api<Stats>(`/v1/teams/${tm.name}/stats`);
          const activity = await api<{ occurred_at: string }[]>(
            `/v1/teams/${tm.name}/activity?limit=1`
          );
          setMeta((old) => ({
            ...old,
            [tm.name]: { stats, lastActivity: activity[0]?.occurred_at },
          }));
        } catch {
          setMeta((old) => ({ ...old, [tm.name]: {} }));
        }
      }
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const visible = projects ? rows.filter((r) => projects.includes(r.name)) : rows;
  const gradientFor = (name: string) =>
    AVATAR_GRADIENTS[
      Math.abs(name.split("").reduce((a, c) => a + c.charCodeAt(0), 0)) % AVATAR_GRADIENTS.length
    ];

  async function create(form: FormData) {
    setError("");
    try {
      await api("/v1/teams", {
        method: "POST",
        body: JSON.stringify({
          name: String(form.get("name")),
          display_name: String(form.get("display_name")) || null,
          description: String(form.get("description")) || null,
          owner: ownerVal || null,
        }),
      });
      setShowCreate(false);
      setOwnerVal("");
      setOwnerQuery("");
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 4 }}>
        <span style={{ flex: 1 }} />
        {me?.is_platform_admin && (
          <button className="primary" onClick={() => setShowCreate(true)}>
            <Plus size={14} style={{ verticalAlign: -2 }} /> {t("projects.create")}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      <p className="muted" style={{ marginTop: 0 }}>{t("projects.pickHint")}</p>
      <div className="proj-grid">
        {visible.map((tm) => {
          const m = meta[tm.name] || {};
          const st = m.stats;
          return (
            <div
              key={tm.name}
              className="card proj-card pcard"
              style={tm.name === current ? { borderColor: "var(--accent)" } : undefined}
              onClick={() => onPick(tm.name)}
            >
              <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                <div className="pcard-avatar" style={{ background: gradientFor(tm.name) }}>
                  {(tm.display_name || tm.name).slice(0, 1).toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h3 style={{ margin: 0, fontSize: 15 }}>{tm.display_name || tm.name}</h3>
                  <div className="muted mono" style={{ fontSize: 12 }}>{tm.name}</div>
                </div>
                <ArrowRight
                  size={16}
                  className="pcard-arrow"
                  style={{ color: "var(--muted)", marginTop: 2 }}
                />
              </div>
              {tm.description && (
                <p className="muted" style={{ fontSize: 12, margin: "10px 0 0" }}>{tm.description}</p>
              )}
              <div className="pcard-stats">
                <span><Boxes size={12} /> {st ? t("projects.res", { count: st.total_resources }) : "…"}</span>
                <span><Users size={12} /> {st ? t("projects.subs", { count: st.subscribers }) : "…"}</span>
                <span><Rocket size={12} /> {st ? t("projects.pub", { count: st.published_last_7d }) : "…"}</span>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
                <span className="badge gray">{t(`roles.${tm.my_role}`, tm.my_role || "")}</span>
                {tm.name === current && (
                  <span className="badge private">{t("projects.current")}</span>
                )}
              </div>
            </div>
          );
        })}
        {visible.length === 0 && (
          <div className="card" style={{ padding: 40, textAlign: "center", width: "100%" }}>
            <Boxes size={32} style={{ color: "var(--muted)" }} />
            <p className="muted" style={{ marginBottom: 0 }}>{t("projects.empty")}</p>
          </div>
        )}
      </div>

      {showCreate && (
        <div className="overlay" onClick={() => setShowCreate(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("projects.create")}</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void create(new FormData(e.currentTarget));
              }}
            >
              <label>{t("projects.name")}</label>
              <input name="name" required placeholder="payment" />
              <label>{t("projects.displayName")}</label>
              <input name="display_name" placeholder="支付平台组" />
              <label>{t("publish.description")}</label>
              <textarea name="description" rows={2} />
              <label>{t("projects.owner")}</label>
              <div className="combo">
                <input
                  value={ownerVal}
                  placeholder={t("projects.ownerPlaceholder")}
                  onChange={(e) => {
                    setOwnerVal(e.target.value);
                    setOwnerQuery(e.target.value);
                  }}
                  onFocus={() => setOwnerQuery(" ")}
                  onBlur={() => setTimeout(() => setOwnerQuery(""), 150)}
                />
                {ownerQuery !== "" && (
                  <div className="combo-list">
                    {users
                      .filter(
                        (u) =>
                          u.username.includes(ownerQuery.toLowerCase()) ||
                          (u.display_name || "").toLowerCase().includes(ownerQuery.toLowerCase())
                      )
                      .slice(0, 8)
                      .map((u) => (
                        <div
                          key={u.username}
                          className="combo-item"
                          onMouseDown={(e) => {
                            e.preventDefault();
                            setOwnerVal(u.username);
                            setOwnerQuery("");
                          }}
                        >
                          <div>
                            <strong>{u.username}</strong>
                            {u.display_name && (
                              <div className="muted" style={{ fontSize: 12 }}>{u.display_name}</div>
                            )}
                          </div>
                        </div>
                      ))}
                  </div>
                )}
              </div>
              <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>{t("projects.ownerHint")}</p>
              {error && <p className="error">{error}</p>}
              <div className="actions">
                <button type="button" className="ghost" onClick={() => setShowCreate(false)}>
                  {t("common.cancel")}
                </button>
                <button className="primary">{t("common.ok")}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
