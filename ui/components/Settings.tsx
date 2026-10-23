"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface MemberRow {
  username: string;
  display_name: string | null;
  role: string;
}
interface AkRow {
  id: string;
  name: string;
  access_key: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
}

export default function Settings({ project }: { project: string }) {
  const { t } = useTranslation();
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [keys, setKeys] = useState<AkRow[]>([]);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<{ ak: string; sk: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setMembers(await api<MemberRow[]>(`/v1/teams/${project}/members`));
      setKeys(await api<AkRow[]>(`/v1/teams/${project}/access-keys`));
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }, [project]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addMember(form: FormData) {
    setError("");
    try {
      await api(`/v1/teams/${project}/members`, {
        method: "POST",
        body: JSON.stringify({
          username: String(form.get("username")),
          role: String(form.get("role")),
        }),
      });
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function removeMember(username: string) {
    await api(`/v1/teams/${project}/members/${username}`, { method: "DELETE" });
    void load();
  }

  async function createKey(form: FormData) {
    setError("");
    try {
      const scopes = ["read", "publish", "deploy"].filter((s) => form.get(`scope_${s}`));
      const res = await api<{ access_key: string; secret: string }>(
        `/v1/teams/${project}/access-keys`,
        {
          method: "POST",
          body: JSON.stringify({ name: String(form.get("name")), scopes }),
        }
      );
      setCreated({ ak: res.access_key, sk: res.secret });
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function revokeKey(id: string) {
    await api(`/v1/teams/${project}/access-keys/${id}`, { method: "DELETE" });
    void load();
  }

  return (
    <div style={{ display: "grid", gap: 28 }}>
      {error && <p className="error">{error}</p>}

      <div>
        <h3>{t("settings.members")}</h3>
        <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 12 }}>
          <table>
            <tbody>
              {members.map((m) => (
                <tr key={m.username}>
                  <td>
                    <strong>{m.username}</strong>
                    {m.display_name && <span className="muted"> · {m.display_name}</span>}
                  </td>
                  <td style={{ width: 110 }}>
                    <span className="badge gray">{t(`roles.${m.role}`, m.role)}</span>
                  </td>
                  <td style={{ width: 90, textAlign: "right" }}>
                    <button className="ghost" onClick={() => void removeMember(m.username)}>
                      {t("common.delete")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); void addMember(new FormData(e.currentTarget)); }} style={{ display: "flex", gap: 8 }}>
          <input name="username" placeholder={t("settings.username")} required />
          <select name="role" defaultValue="member">
            <option value="admin">{t("roles.admin")}</option>
            <option value="publisher">{t("roles.publisher")}</option>
            <option value="member">{t("roles.member")}</option>
          </select>
          <button className="primary">{t("settings.addMember")}</button>
        </form>
      </div>

      <div>
        <h3>{t("aksk.heading")}</h3>
        <p className="muted" style={{ marginTop: -6 }}>{t("aksk.hint")}</p>
        <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 12 }}>
          <table>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td>
                    <strong>{k.name}</strong>
                    <div className="muted" style={{ fontSize: 12, fontFamily: "monospace" }}>{k.access_key}</div>
                  </td>
                  <td>
                    {k.scopes.map((s) => (
                      <span key={s} className="badge gray" style={{ marginRight: 4 }}>
                        {t(`scopes.${s}`, s)}
                      </span>
                    ))}
                  </td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {k.last_used_at ? t("aksk.lastUsed", { time: k.last_used_at.slice(0, 16).replace("T", " ") }) : t("aksk.neverUsed")}
                  </td>
                  <td style={{ width: 90, textAlign: "right" }}>
                    {k.revoked ? (
                      <span className="badge revoked">{t("aksk.revoked")}</span>
                    ) : (
                      <button className="danger" onClick={() => void revokeKey(k.id)}>
                        {t("aksk.revoke")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {keys.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted" style={{ textAlign: "center", padding: 20 }}>
                    {t("aksk.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); void createKey(new FormData(e.currentTarget)); }} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input name="name" placeholder={t("aksk.keyName")} required />
          {["read", "publish", "deploy"].map((s) => (
            <label key={s} style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--muted)" }}>
              <input type="checkbox" name={`scope_${s}`} defaultChecked style={{ width: "auto" }} /> {t(`scopes.${s}`)}
            </label>
          ))}
          <button className="primary">{t("aksk.create")}</button>
        </form>
      </div>

      {created && (
        <div className="overlay" onClick={() => setCreated(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("aksk.createdTitle")}</h3>
            <p className="muted">{t("aksk.createdHint")}</p>
            <label>{t("aksk.ak")}</label>
            <pre className="sk">{created.ak}</pre>
            <label>{t("aksk.sk")}</label>
            <pre className="sk">{created.sk}</pre>
            <div className="actions">
              <button className="primary" onClick={() => setCreated(null)}>
                {t("common.ok")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
