"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, errMsg, withBusy } from "../lib/api";

interface AuditRow {
  id: number;
  occurred_at: string;
  actor: string | null;
  action: string;
  kind: string | null;
  namespace: string | null;
  name: string | null;
  detail: Record<string, unknown>;
  source_ip: string | null;
}

const PAGE = 50;

export default function Audit() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const load = useCallback(
    async (offset: number) => {
      try {
        let data: AuditRow[] = [];
        await withBusy(setBusy, async () => {
          data = await api<AuditRow[]>(`/v1/audit?limit=${PAGE}&offset=${offset}`);
        });
        setRows((prev) => (offset === 0 ? data : [...prev, ...data]));
        if (data.length < PAGE) setDone(true);
      } catch (e) {
        setError(errMsg(e));
      }
    },
    []
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  return (
    <section>
      <h2>{t("audit.title")}</h2>
      <p className="muted">{t("audit.subtitle")}</p>
      {error && <div className="error">{error}</div>}
      {rows.length === 0 && !busy && !error && <p className="muted">{t("audit.empty")}</p>}
      {rows.length > 0 && (
        <table className="table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>{t("audit.when")}</th>
              <th>{t("audit.actor")}</th>
              <th>{t("audit.action")}</th>
              <th>{t("audit.target")}</th>
              <th>{t("audit.detail")}</th>
              <th>{t("audit.sourceIp")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>
                  {new Date(r.occurred_at).toLocaleString()}
                </td>
                <td>{r.actor ?? "—"}</td>
                <td>
                  <code>{r.action}</code>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {r.kind ? `${r.kind}/${r.namespace}/${r.name}` : "—"}
                </td>
                <td
                  className="muted"
                  style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis" }}
                  title={JSON.stringify(r.detail)}
                >
                  {Object.keys(r.detail).length ? JSON.stringify(r.detail) : "—"}
                </td>
                <td className="muted">{r.source_ip ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!done && (
        <button className="btn" disabled={busy} onClick={() => void load(rows.length)}>
          {busy ? t("common.loading") : t("audit.loadMore")}
        </button>
      )}
    </section>
  );
}