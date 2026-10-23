"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface SubRow {
  id: string;
  subscriber_team: string;
  kind: string;
  namespace: string;
  name: string;
  status: string;
}

export default function Subscriptions({ project }: { project: string }) {
  const { t } = useTranslation();
  const [mine, setMine] = useState<SubRow[]>([]);
  const [pending, setPending] = useState<SubRow[]>([]);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(async () => {
    try {
      const mineData = await api<{ items: SubRow[] }>(`/v1/teams/${project}/subscriptions`);
      setMine(mineData.items);
      const pendingData = await api<{ items: SubRow[] }>(
        `/v1/teams/${project}/subscriptions/pending`
      );
      setPending(pendingData.items);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }, [project]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(form: FormData) {
    setError("");
    try {
      await api(`/v1/teams/${project}/subscriptions`, {
        method: "POST",
        body: JSON.stringify({
          kind: String(form.get("kind")),
          namespace: String(form.get("namespace")),
          name: String(form.get("name")) || "*",
        }),
      });
      setShowNew(false);
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function decide(id: string, approve: boolean) {
    await api(`/v1/subscriptions/${id}/${approve ? "approve" : "reject"}`, { method: "POST" });
    void load();
  }

  async function revoke(id: string) {
    await api(`/v1/subscriptions/${id}`, { method: "DELETE" });
    void load();
  }

  return (
    <div style={{ display: "grid", gap: 24 }}>
      {error && <p className="error">{error}</p>}

      <div>
        <div style={{ display: "flex", marginBottom: 12 }}>
          <h3 style={{ margin: 0, flex: 1 }}>{t("subs.pending")}</h3>
        </div>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <tbody>
              {pending.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>{s.subscriber_team}</strong>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {s.kind} {s.namespace}/{s.name}
                    </div>
                  </td>
                  <td style={{ width: 180, textAlign: "right" }}>
                    <button className="primary" onClick={() => void decide(s.id, true)}>
                      {t("subs.approve")}
                    </button>{" "}
                    <button className="danger" onClick={() => void decide(s.id, false)}>
                      {t("subs.reject")}
                    </button>
                  </td>
                </tr>
              ))}
              {pending.length === 0 && (
                <tr>
                  <td className="muted" style={{ textAlign: "center", padding: 20 }}>
                    {t("subs.noPending")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div style={{ display: "flex", marginBottom: 12 }}>
          <h3 style={{ margin: 0, flex: 1 }}>{t("subs.mine")}</h3>
          <button className="primary" onClick={() => setShowNew(true)}>
            + {t("subs.subscribe")}
          </button>
        </div>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <tbody>
              {mine.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>
                      {s.kind} {s.namespace}/{s.name}
                    </strong>
                  </td>
                  <td style={{ width: 130 }}>
                    <span className={`badge ${s.status}`}>{t(`subs.status.${s.status}`)}</span>
                  </td>
                  <td style={{ width: 90, textAlign: "right" }}>
                    {s.status !== "revoked" && (
                      <button className="ghost" onClick={() => void revoke(s.id)}>
                        {t("subs.revoke")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {mine.length === 0 && (
                <tr>
                  <td className="muted" style={{ textAlign: "center", padding: 20 }}>
                    {t("subs.noMine")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showNew && (
        <div className="overlay" onClick={() => setShowNew(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("subs.subscribe")}</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void create(new FormData(e.currentTarget));
              }}
            >
              <label>{t("subs.targetKind")}</label>
              <select name="kind" defaultValue="MCPServer">
                <option>Agent</option>
                <option>MCPServer</option>
                <option>Skill</option>
              </select>
              <label>{t("subs.targetNamespace")}</label>
              <input name="namespace" required placeholder="payment" />
              <label>{t("subs.targetName")}</label>
              <input name="name" placeholder="payment-gateway" />
              <div className="actions">
                <button type="button" className="ghost" onClick={() => setShowNew(false)}>
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
