"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, errMsg, withBusy } from "../lib/api";

interface SubRow {
  id: string;
  subscriber_team: string;
  kind: string;
  namespace: string;
  name: string;
  status: string;
  pinned_tag?: string | null;
}

interface PoolRow {
  kind: string;
  namespace: string;
  name: string;
  visibility: string;
  description: string | null;
  latest_version: { tag: string | null; version: number } | null;
}

/** Searchable select: input filters a dropdown fed by a resource pool. */
function SearchSelect({
  placeholder,
  value,
  onPick,
  options,
  pick,
  render,
}: {
  placeholder: string;
  value: string;
  onPick: (v: string) => void;
  options: PoolRow[];
  pick: (r: PoolRow) => string;
  render: (r: PoolRow) => { title: string; sub: string };
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return options.filter(
      (o) =>
        o.namespace.toLowerCase().includes(q) ||
        o.name.toLowerCase().includes(q) ||
        (o.description || "").toLowerCase().includes(q)
    );
  }, [options, query]);

  return (
    <div className="combo">
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          onPick(e.target.value);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && (
        <div className="combo-list">
          {filtered.map((o) => {
            const { title, sub } = render(o);
            return (
              <div
                key={`${o.namespace}/${o.name}`}
                className="combo-item"
                onMouseDown={(e) => {
                  e.preventDefault();
                  onPick(pick(o));
                  setQuery("");
                  setOpen(false);
                }}
              >
                <div>
                  <strong>{title}</strong>
                  {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
                </div>
                <span className={`badge ${o.visibility}`}>
                  {t(`visibility.${o.visibility}`, o.visibility)}
                </span>
              </div>
            );
          })}
          {filtered.length === 0 && <div className="combo-item muted">{t("subs.noMatch")}</div>}
        </div>
      )}
    </div>
  );
}

export default function Subscriptions({ project }: { project: string }) {
  const { t } = useTranslation();
  const [mine, setMine] = useState<SubRow[]>([]);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [kindSel, setKindSel] = useState("MCPServer");
  const [pool, setPool] = useState<PoolRow[]>([]);
  const [nsVal, setNsVal] = useState("");
  const [nameVal, setNameVal] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const mineData = await api<{ items: SubRow[] }>(`/v1/teams/${project}/subscriptions`);
      setMine(mineData.items);

    } catch (e) {
      setError(errMsg(e));
    }
  }, [project]);

  useEffect(() => {
    void load();
  }, [load]);

  // Load the visible catalog for the chosen kind whenever the dialog opens
  // or the kind changes — this powers both searchable dropdowns.
  useEffect(() => {
    if (!showNew) return;
    void api<{ items: PoolRow[] }>(`/v1/resources?kind=${kindSel}&limit=200`)
      .then((d) => setPool(d.items))
      .catch((e) => setError(errMsg(e)));
  }, [showNew, kindSel]);

  const namespaces = useMemo(
    () => Array.from(new Set(pool.map((p) => p.namespace))).sort(),
    [pool]
  );
  const namePool = useMemo(() => pool.filter((p) => p.namespace === nsVal), [pool, nsVal]);

  async function create() {
    setError("");
    try {
      await api(`/v1/teams/${project}/subscriptions`, {
        method: "POST",
        body: JSON.stringify({
          kind: kindSel,
          namespace: nsVal,
          name: nameVal || "*",
        }),
      });
      setShowNew(false);
      setNsVal("");
      setNameVal("");
      void load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  function revoke(s: SubRow) {
    if (!confirm(t("subs.confirmRevoke", { target: `${s.kind} ${s.namespace}/${s.name}` }))) return;
    void withBusy(setBusy, async () => {
      await api(`/v1/subscriptions/${s.id}`, { method: "DELETE" });
      void load();
    }, (e) => setError(errMsg(e)));
  }

  return (
    <div style={{ display: "grid", gap: 24 }}>
      {error && <p className="error">{error}</p>}

      <div>
        <div style={{ display: "flex", marginBottom: 12 }}>
          <h3 style={{ margin: 0, flex: 1 }}>{t("subs.mine")}</h3>
          <button
            className="primary"
            onClick={() => {
              setShowNew(true);
              setNsVal("");
              setNameVal("");
            }}
          >
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
                    {s.pinned_tag && (
                      <span className="badge internal" title={t("subs.pinnedHint")}>
                        📌 {s.pinned_tag}
                      </span>
                    )}
                  </td>
                  <td style={{ width: 90, textAlign: "right" }}>
                    {s.status !== "revoked" && (
                      <button className="ghost" disabled={busy} onClick={() => revoke(s)}>
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
            <label>{t("subs.targetKind")}</label>
            <select
              value={kindSel}
              onChange={(e) => {
                setKindSel(e.target.value);
                setNsVal("");
                setNameVal("");
              }}
            >
              <option>Agent</option>
              <option>MCPServer</option>
              <option>Skill</option>
            </select>

            <label>{t("subs.targetNamespace")}</label>
            <SearchSelect
              placeholder={t("subs.searchNamespace")}
              value={nsVal}
              onPick={setNsVal}
              options={pool.filter((p, i) => namespaces.indexOf(p.namespace) === i)}
              pick={(o) => o.namespace}
              render={(o) => ({ title: o.namespace, sub: "" })}
            />

            <label>{t("subs.targetName")}</label>
            <SearchSelect
              placeholder={nsVal ? t("subs.searchName") : t("subs.pickNamespaceFirst")}
              value={nameVal}
              onPick={setNameVal}
              options={namePool}
              pick={(o) => o.name}
              render={(o) => ({
                title: o.name,
                sub: `${o.latest_version?.tag || `v${o.latest_version?.version ?? "-"}`}${
                  o.description ? " · " + o.description : ""
                }`,
              })}
            />
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
              {t("subs.wholeNamespaceHint")}
            </p>

            <div className="actions">
              <button type="button" className="ghost" onClick={() => setShowNew(false)}>
                {t("common.cancel")}
              </button>
              <button className="primary" disabled={!nsVal} onClick={() => void create()}>
                {t("common.ok")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
