"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, errMsg, withBusy } from "../lib/api";

interface GrantRow {
  id: string;
  subscriber_team: string;
  kind: string;
  namespace: string;
  name: string;
  status: string;
  since: string;
}

export default function Grants({ project }: { project: string }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<GrantRow[]>([]);
  const [granted, setGranted] = useState<GrantRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const pendingData = await api<{ items: GrantRow[] }>(
        `/v1/teams/${project}/subscriptions/pending`
      );
      setPending(pendingData.items);
      // 消费方图谱 = 已授权列表(active 订阅)
      const consumers = await api<GrantRow[]>(`/v1/teams/${project}/consumers`);
      setGranted(consumers);
    } catch (e) {
      setError(errMsg(e));
    }
  }, [project]);

  useEffect(() => {
    void load();
  }, [load]);

  function decide(id: string, approve: boolean) {
    setError("");
    void withBusy(setBusy, async () => {
      await api(`/v1/subscriptions/${id}/${approve ? "approve" : "reject"}`, { method: "POST" });
      void load();
    }, (e) => setError(errMsg(e)));
  }

  function revoke(id: string) {
    if (!confirm(t("grants.confirmRevoke"))) return;
    setError("");
    void withBusy(setBusy, async () => {
      await api(`/v1/subscriptions/${id}`, { method: "DELETE" });
      void load();
    }, (e) => setError(errMsg(e)));
  }

  return (
    <div style={{ display: "grid", gap: 24 }}>
      {error && <p className="error">{error}</p>}

      <div>
        <div style={{ display: "flex", marginBottom: 12 }}>
          <h3 style={{ margin: 0, flex: 1 }}>{t("grants.pending")}</h3>
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
                    <button className="primary" disabled={busy} onClick={() => decide(s.id, true)}>
                      {t("subs.approve")}
                    </button>{" "}
                    <button className="danger" disabled={busy} onClick={() => decide(s.id, false)}>
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
          <h3 style={{ margin: 0, flex: 1 }}>{t("grants.active")}</h3>
        </div>
        <p className="muted" style={{ marginTop: -6 }}>{t("grants.activeHint")}</p>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <tbody>
              {granted.map((g) => (
                <tr key={g.id}>
                  <td>
                    <strong>{g.subscriber_team}</strong>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {g.kind} {g.namespace}/{g.name}
                    </div>
                  </td>
                  <td style={{ width: 150 }}>
                    <span className={`badge ${g.status}`}>{t(`subs.status.${g.status}`)}</span>
                  </td>
                  <td className="muted" style={{ fontSize: 12, width: 130 }}>
                    {t("grants.since", { time: g.since.slice(0, 10) })}
                  </td>
                  <td style={{ width: 110, textAlign: "right" }}>
                    <button className="danger" disabled={busy} onClick={() => revoke(g.id)}>
                      {t("grants.revoke")}
                    </button>
                  </td>
                </tr>
              ))}
              {granted.length === 0 && (
                <tr>
                  <td className="muted" style={{ textAlign: "center", padding: 20 }}>
                    {t("grants.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
