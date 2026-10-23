"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface TeamRow {
  name: string;
  display_name: string | null;
  my_role: string | null;
}

export default function Projects({ onEnter }: { onEnter: (name: string) => void }) {
  const { t } = useTranslation();
  const [teams, setTeams] = useState<TeamRow[]>([]);
  const [me, setMe] = useState<{ is_platform_admin: boolean } | null>(null);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  async function load() {
    try {
      setTeams(await api<TeamRow[]>("/v1/teams"));
      setMe(await api<{ is_platform_admin: boolean }>("/v1/auth/me"));
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function create(form: FormData) {
    try {
      await api("/v1/teams", {
        method: "POST",
        body: JSON.stringify({
          name: String(form.get("name")),
          display_name: String(form.get("display_name")) || null,
          description: String(form.get("description")) || null,
        }),
      });
      setShowCreate(false);
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  return (
    <main className="content" style={{ margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
        <h2 className="page" style={{ margin: 0 }}>
          {t("projects.heading")}
        </h2>
        <span style={{ flex: 1 }} />
        {me?.is_platform_admin && (
          <button className="primary" onClick={() => setShowCreate(true)}>
            + {t("projects.create")}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="proj-grid">
        {teams.map((tm) => (
          <div key={tm.name} className="card proj-card" onClick={() => onEnter(tm.name)}>
            <h3 style={{ margin: "0 0 6px" }}>{tm.display_name || tm.name}</h3>
            <div className="muted" style={{ fontSize: 13 }}>
              {tm.name}
            </div>
            <div style={{ marginTop: 12 }}>
              <span className="badge gray">{tm.my_role || "-"}</span>
            </div>
          </div>
        ))}
        {teams.length === 0 && <p className="muted">{t("projects.empty")}</p>}
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
    </main>
  );
}
