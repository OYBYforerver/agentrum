"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface TeamRow {
  name: string;
  display_name: string | null;
  my_role: string | null;
}

/** Project card wall rendered INSIDE the workspace shell — switching context
 * without leaving the frame (GitHub/Vercel pattern). */
export default function ProjectsInline({
  projects,
  current,
  onPick,
}: {
  projects: string[];
  current: string;
  onPick: (name: string) => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<TeamRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<TeamRow[]>("/v1/teams")
      .then(setRows)
      .catch((e) => setError(String(e).replace("Error: ", "")));
  }, []);

  const visible = rows.filter((r) => projects.includes(r.name));

  return (
    <div>
      <h2 className="page">{t("projects.heading")}</h2>
      {error && <p className="error">{error}</p>}
      <div className="proj-grid">
        {visible.map((tm) => (
          <div
            key={tm.name}
            className="card proj-card"
            style={tm.name === current ? { borderColor: "var(--accent)" } : undefined}
            onClick={() => onPick(tm.name)}
          >
            <h3 style={{ margin: "0 0 6px" }}>{tm.display_name || tm.name}</h3>
            <div className="muted" style={{ fontSize: 13 }}>{tm.name}</div>
            <div style={{ marginTop: 12 }}>
              <span className="badge gray">{t(`roles.${tm.my_role}`, tm.my_role || "")}</span>
              {tm.name === current && (
                <span className="badge private" style={{ marginLeft: 6 }}>{t("projects.current")}</span>
              )}
            </div>
          </div>
        ))}
        {visible.length === 0 && <p className="muted">{t("projects.empty")}</p>}
      </div>
    </div>
  );
}
