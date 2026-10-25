"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, errMsg, withBusy } from "../lib/api";

interface UserRow {
  username: string;
  display_name: string | null;
  is_platform_admin: boolean;
  disabled: boolean;
}

interface TeamRow {
  name: string;
  display_name: string | null;
  description: string | null;
}

interface MemberRow {
  username: string;
  role: string;
}

export default function Admin() {
  const { t } = useTranslation();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [teams, setTeams] = useState<(TeamRow & { members?: number })[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [pwFor, setPwFor] = useState<string | null>(null);
  const [pwVal, setPwVal] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      let rows: UserRow[] = [];
      let teamRows: TeamRow[] = [];
      await withBusy(setBusy, async () => {
        rows = await api<UserRow[]>("/v1/users");
        teamRows = await api<TeamRow[]>("/v1/teams");
      });
      setUsers(rows);
      // Member counts are nice-to-have; failures leave the count blank.
      const counted = await Promise.all(
        teamRows.map(async (tm) => {
          try {
            const ms = await api<MemberRow[]>(`/v1/teams/${tm.name}/members`);
            return { ...tm, members: ms.length };
          } catch {
            return { ...tm };
          }
        })
      );
      setTeams(counted);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchUser(username: string, body: Record<string, unknown>, okMsg: string) {
    setError("");
    setNotice("");
    try {
      await api(`/v1/users/${username}`, { method: "PATCH", body: JSON.stringify(body) });
      setNotice(okMsg);
      void load();
    } catch (e) {
      setError(errMsg(e)); // e.g. last-platform-admin protection
    }
  }

  async function createUser(form: FormData) {
    setError("");
    try {
      await api("/v1/users", {
        method: "POST",
        body: JSON.stringify({
          username: String(form.get("username")),
          password: String(form.get("password")),
          display_name: String(form.get("display_name")) || null,
        }),
      });
      setCreating(false);
      void load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function resetPassword() {
    if (!pwFor) return;
    try {
      await api(`/v1/users/${pwFor}`, {
        method: "PATCH",
        body: JSON.stringify({ new_password: pwVal }),
      });
      setPwFor(null);
      setPwVal("");
      setNotice(t("admin.pwResetDone", { user: pwFor }));
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <section>
      <h2>{t("admin.title")}</h2>
      <p className="muted">{t("admin.subtitle")}</p>
      {error && <div className="error">{error}</div>}
      {notice && <p className="muted">{notice}</p>}

      <h3 style={{ marginTop: 24 }}>{t("admin.users")}</h3>
      <div style={{ marginBottom: 10 }}>
        <button className="primary" disabled={busy} onClick={() => setCreating(true)}>
          {t("admin.createUser")}
        </button>
      </div>
      {users.length === 0 && !busy && <p className="muted">{t("admin.empty")}</p>}
      {users.length > 0 && (
        <table className="table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>{t("admin.username")}</th>
              <th>{t("admin.displayName")}</th>
              <th>{t("admin.platformAdmin")}</th>
              <th>{t("admin.status")}</th>
              <th style={{ textAlign: "right" }}>{t("admin.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.username}>
                <td>
                  <strong>{u.username}</strong>
                </td>
                <td className="muted">{u.display_name ?? "—"}</td>
                <td>
                  {u.is_platform_admin ? (
                    <span className="badge internal">{t("admin.yes")}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {u.disabled ? (
                    <span className="badge restricted">{t("admin.disabled")}</span>
                  ) : (
                    <span className="badge active">{t("admin.active")}</span>
                  )}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button
                    className="ghost"
                    onClick={() =>
                      void patchUser(
                        u.username,
                        { is_platform_admin: !u.is_platform_admin },
                        t("admin.updated")
                      )
                    }
                  >
                    {u.is_platform_admin ? t("admin.revokeAdmin") : t("admin.grantAdmin")}
                  </button>{" "}
                  <button className="ghost" onClick={() => setPwFor(u.username)}>
                    {t("admin.resetPw")}
                  </button>{" "}
                  <button
                    className={u.disabled ? "ghost" : "danger"}
                    onClick={() =>
                      void patchUser(
                        u.username,
                        { disabled: !u.disabled },
                        t("admin.updated")
                      )
                    }
                  >
                    {u.disabled ? t("admin.enable") : t("admin.disable")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 style={{ marginTop: 32 }}>{t("admin.projects")}</h3>
      <p className="muted" style={{ marginTop: 0 }}>{t("admin.projectsHint")}</p>
      {teams.length === 0 && !busy && <p className="muted">{t("admin.empty")}</p>}
      {teams.length > 0 && (
        <table className="table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>{t("admin.project")}</th>
              <th>{t("admin.displayName")}</th>
              <th>{t("admin.members")}</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((tm) => (
              <tr key={tm.name}>
                <td>
                  <strong>{tm.name}</strong>
                </td>
                <td className="muted">{tm.display_name ?? "—"}</td>
                <td>{tm.members ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && (
        <div className="overlay" onClick={() => setCreating(false)}>
          <form
            className="dialog"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              void createUser(new FormData(e.currentTarget));
            }}
          >
            <h3>{t("admin.createUser")}</h3>
            <input name="username" placeholder={t("admin.username")} required minLength={2} />
            <input
              name="password"
              type="password"
              placeholder={t("admin.password")}
              required
              minLength={8}
            />
            <input name="display_name" placeholder={t("admin.displayName")} />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" className="ghost" onClick={() => setCreating(false)}>
                {t("common.cancel")}
              </button>
              <button type="submit" className="primary">
                {t("common.create")}
              </button>
            </div>
          </form>
        </div>
      )}

      {pwFor && (
        <div className="overlay" onClick={() => setPwFor(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("admin.resetPwFor", { user: pwFor })}</h3>
            <input
              type="password"
              value={pwVal}
              onChange={(e) => setPwVal(e.target.value)}
              placeholder={t("admin.password")}
              minLength={8}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="ghost" onClick={() => setPwFor(null)}>
                {t("common.cancel")}
              </button>
              <button className="primary" disabled={pwVal.length < 8} onClick={() => void resetPassword()}>
                {t("admin.resetPw")}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
