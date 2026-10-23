"use client";

import "../lib/i18n";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, getServer, getToken, setServer, setToken } from "../lib/api";
import { setLocale } from "../lib/i18n";

type Tab = "catalog" | "publish" | "subscriptions";

interface ResourceRow {
  kind: string;
  namespace: string;
  name: string;
  visibility: string;
  updated_at: string;
  latest_version: { tag: string | null; version: number; change_notes: string | null } | null;
}

interface SubRow {
  id: string;
  subscriber_team: string;
  kind: string;
  namespace: string;
  name: string;
  status: string;
}

export default function Home() {
  const { t, i18n } = useTranslation();
  const [authed, setAuthed] = useState(false);
  const [tab, setTab] = useState<Tab>("catalog");
  const [server, setServerField] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [mine, setMine] = useState<SubRow[]>([]);
  const [pending, setPending] = useState<SubRow[]>([]);
  const [me, setMe] = useState<{ username: string; is_platform_admin: boolean } | null>(null);
  const [lang, setLangState] = useState<"zh" | "en">("zh");

  useEffect(() => {
    setLangState((i18n.language || "zh").startsWith("zh") ? "zh" : "en");
    // OIDC callback may deliver the token via ?token=
    const url = new URL(window.location.href);
    const urlToken = url.searchParams.get("token");
    if (urlToken) {
      setToken(urlToken);
      window.history.replaceState({}, "", "/");
    }
    if (getToken()) setAuthed(true);
    setServerField(getServer());
  }, [i18n.language]);

  const loadCatalog = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (search) params.set("q", search);
      if (kindFilter) params.set("kind", kindFilter);
      const data = await api<{ items: ResourceRow[] }>(`/v1/resources?${params}`);
      setRows(data.items);
    } catch (e) {
      setError(String(e));
    }
  }, [search, kindFilter]);

  const loadSubs = useCallback(async () => {
    try {
      const meData = await api<{ username: string; is_platform_admin: boolean }>("/v1/auth/me");
      setMe(meData);
      const teams = await api<{ name: string; my_role: string }[]>("/v1/teams");
      const allMine: SubRow[] = [];
      for (const team of teams) {
        const data = await api<{ items: SubRow[] }>(`/v1/teams/${team.name}/subscriptions`);
        allMine.push(...data.items);
      }
      setMine(allMine);
      const allPending: SubRow[] = [];
      for (const team of teams) {
        const data = await api<{ items: SubRow[] }>(
          `/v1/teams/${team.name}/subscriptions/pending`
        );
        allPending.push(...data.items);
      }
      setPending(allPending);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    void loadCatalog();
    void loadSubs();
  }, [authed, loadCatalog, loadSubs]);

  async function doLogin() {
    setError("");
    try {
      setServer(server);
      const data = await api<{ access_token: string }>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(data.access_token);
      setAuthed(true);
    } catch (e) {
      setError(t("login.error", { detail: String(e).replace("Error: ", "") }));
    }
  }

  async function doPublish(form: FormData) {
    setError("");
    try {
      const body = {
        spec: JSON.parse(String(form.get("spec") || "{}")),
        tag: String(form.get("tag") || "") || null,
        description: String(form.get("description") || "") || null,
        visibility: String(form.get("visibility")),
      };
      const kind = String(form.get("kind"));
      const ns = String(form.get("namespace"));
      const name = String(form.get("name"));
      await api(`/v1/resources/${kind}/${ns}/${name}`, { method: "PUT", body: JSON.stringify(body) });
      setError("");
      alert(t("publish.success", { kind, namespace: ns, name }));
      setTab("catalog");
      void loadCatalog();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function decide(id: string, approve: boolean) {
    await api(`/v1/subscriptions/${id}/${approve ? "approve" : "reject"}`, { method: "POST" });
    void loadSubs();
  }

  async function revoke(id: string) {
    await api(`/v1/subscriptions/${id}`, { method: "DELETE" });
    void loadSubs();
  }

  if (!authed) {
    return (
      <main style={{ maxWidth: 420, margin: "10vh auto", padding: 24 }}>
        <h1 style={{ textAlign: "center" }}>{t("app.title")}</h1>
        <p style={{ textAlign: "center", color: "#94a3b8" }}>{t("app.tagline")}</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void doLogin();
          }}
          style={{ display: "grid", gap: 12 }}
        >
          <label>{t("login.server")}</label>
          <input value={server} onChange={(e) => setServerField(e.target.value)} />
          <label>{t("login.username")}</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label>{t("login.password")}</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <span className="error">{error}</span>}
          <button className="primary" type="submit">
            {t("login.submit")}
          </button>
        </form>
        <div style={{ textAlign: "center", marginTop: 20 }}>
          <select
            value={lang}
            onChange={(e) => {
              setLocale(e.target.value as "zh" | "en");
              setLangState(e.target.value as "zh" | "en");
            }}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 1080, margin: "0 auto", padding: 24 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <h2 style={{ margin: 0 }}>{t("app.title")}</h2>
        {(["catalog", "publish", "subscriptions"] as Tab[]).map((key) => (
          <button key={key} className={tab === key ? "primary" : "ghost"} onClick={() => setTab(key)}>
            {t(`nav.${key}`)}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <span style={{ color: "#94a3b8" }}>{me?.username}</span>
        <select
          value={lang}
          onChange={(e) => {
            setLocale(e.target.value as "zh" | "en");
            setLangState(e.target.value as "zh" | "en");
          }}
        >
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
        <button
          className="ghost"
          onClick={() => {
            localStorage.removeItem("agentrum-token");
            setAuthed(false);
          }}
        >
          {t("nav.logout")}
        </button>
      </header>
      {error && <p className="error">{error}</p>}

      {tab === "catalog" && (
        <section style={{ marginTop: 24 }}>
          <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
            <input
              placeholder={t("catalog.search")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1 }}
            />
            <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
              <option value="">{t("catalog.allKinds")}</option>
              {["Agent", "MCPServer", "Skill", "Prompt", "Secret", "Deployment"].map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={() => void loadCatalog()}>
              ⟳
            </button>
          </div>
          <table>
            <thead>
              <tr>
                {["kind", "name", "namespace", "visibility", "tag", "updated"].map((c) => (
                  <th key={c}>{t(`catalog.columns.${c}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.kind}/${r.namespace}/${r.name}`}>
                  <td>{r.kind}</td>
                  <td>{r.name}</td>
                  <td>{r.namespace}</td>
                  <td>
                    <span className={`badge ${r.visibility}`}>
                      {r.visibility === "restricted" ? t("catalog.restricted") : r.visibility}
                    </span>
                  </td>
                  <td>{r.latest_version?.tag || `v${r.latest_version?.version ?? "-"}`}</td>
                  <td>{r.updated_at.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p style={{ color: "#94a3b8" }}>{t("catalog.empty")}</p>}
        </section>
      )}

      {tab === "publish" && (
        <section style={{ marginTop: 24, maxWidth: 640 }}>
          <h3>{t("publish.heading")}</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void doPublish(new FormData(e.currentTarget));
            }}
            style={{ display: "grid", gap: 12 }}
          >
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <select name="kind" defaultValue="Agent">
                {["Agent", "MCPServer", "Skill", "Prompt", "Secret", "Deployment"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
              <input name="namespace" placeholder={t("publish.namespace")} defaultValue="default" required />
              <input name="name" placeholder={t("publish.name")} required />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <input name="tag" placeholder={t("publish.tag")} />
              <select name="visibility" defaultValue="internal">
                <option value="internal">internal</option>
                <option value="restricted">restricted</option>
              </select>
            </div>
            <textarea name="description" placeholder={t("publish.description")} rows={2} />
            <textarea
              name="spec"
              rows={8}
              placeholder='{"image": "registry.internal/x:1.0"}'
              defaultValue='{"image": "registry.internal/my-agent:0.1.0"}'
            />
            <small style={{ color: "#94a3b8" }}>{t("publish.hint")}</small>
            <button className="primary" type="submit">
              {t("publish.submit")}
            </button>
          </form>
        </section>
      )}

      {tab === "subscriptions" && (
        <section style={{ marginTop: 24 }}>
          {pending.length > 0 && (
            <>
              <h3>{t("subs.pending")}</h3>
              <table>
                <tbody>
                  {pending.map((s) => (
                    <tr key={s.id}>
                      <td>{s.subscriber_team}</td>
                      <td>
                        {s.kind} {s.namespace}/{s.name}
                      </td>
                      <td>
                        <span className={`badge ${s.status}`}>{t(`subs.status.${s.status}`)}</span>
                      </td>
                      <td>
                        <button className="primary" onClick={() => void decide(s.id, true)}>
                          {t("subs.approve")}
                        </button>{" "}
                        <button className="ghost" onClick={() => void decide(s.id, false)}>
                          {t("subs.reject")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3>{t("subs.mine")}</h3>
          <table>
            <tbody>
              {mine.map((s) => (
                <tr key={s.id}>
                  <td>{s.subscriber_team}</td>
                  <td>
                    {s.kind} {s.namespace}/{s.name}
                  </td>
                  <td>
                    <span className={`badge ${s.status}`}>{t(`subs.status.${s.status}`)}</span>
                  </td>
                  <td>
                    {s.status !== "revoked" && (
                      <button className="ghost" onClick={() => void revoke(s.id)}>
                        {t("subs.revoke")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
