"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface ResourceRow {
  kind: string;
  namespace: string;
  name: string;
  visibility: string;
  description: string | null;
  updated_at: string;
  secret_keys: string[] | null;
  latest_version: { tag: string | null; version: number; change_notes: string | null } | null;
}

interface VersionRow {
  version: number;
  tag: string | null;
  spec: Record<string, unknown>;
  change_notes: string | null;
  published_by: string;
  created_at: string;
}

const KIND_FIELDS: Record<string, { key: string; labelKey: string; placeholder?: string }[]> = {
  Agent: [
    { key: "image", labelKey: "image", placeholder: "registry.internal/my-agent:1.0.0" },
    { key: "framework", labelKey: "framework", placeholder: "langgraph" },
  ],
  MCPServer: [
    { key: "transport", labelKey: "transport" },
    { key: "endpoint", labelKey: "endpoint", placeholder: "http://host:3000/mcp" },
    { key: "command", labelKey: "command" },
  ],
  Skill: [
    { key: "source_url", labelKey: "source_url", placeholder: "https://git.internal/pay/skills.git" },
    { key: "source_ref", labelKey: "source_ref", placeholder: "main / v1.2.0 / commit-sha" },
    { key: "source_subdirectory", labelKey: "source_subdirectory", placeholder: "skills/gateway" },
    { key: "source_credentials_ref", labelKey: "source_credentials_ref", placeholder: "git-creds (Secret)" },
    { key: "entrypoint", labelKey: "entrypoint", placeholder: "SKILL.md" },
    { key: "instructions", labelKey: "instructions" },
  ],
  Prompt: [{ key: "template", labelKey: "template", placeholder: "评审以下变更: {{code}}" }],
  Secret: [{ key: "data", labelKey: "data" }],
  Deployment: [
    { key: "target_kind", labelKey: "target_kind" },
    { key: "target_namespace", labelKey: "target_namespace" },
    { key: "target_name", labelKey: "target_name" },
    { key: "cluster_namespace", labelKey: "cluster_namespace" },
    { key: "replicas", labelKey: "replicas" },
  ],
};

function buildSpec(kind: string, form: FormData): Record<string, unknown> {
  const val = (k: string) => String(form.get(k) || "").trim();
  if (kind === "Agent") {
    const s: Record<string, unknown> = { image: val("f_image") };
    if (val("f_framework")) s.framework = val("f_framework");
    return s;
  }
  if (kind === "MCPServer") {
    const s: Record<string, unknown> = { transport: val("f_transport") };
    if (val("f_endpoint")) s.endpoint = val("f_endpoint");
    if (val("f_command")) s.command = val("f_command");
    return s;
  }
  if (kind === "Skill") {
    const s: Record<string, unknown> = {};
    if (val("f_source_url")) {
      const git: Record<string, unknown> = { url: val("f_source_url") };
      if (val("f_source_ref")) git.ref = val("f_source_ref");
      if (val("f_source_subdirectory")) git.subdirectory = val("f_source_subdirectory");
      if (val("f_source_credentials_ref")) git.credentials_ref = val("f_source_credentials_ref");
      s.source = { git };
    }
    if (val("f_entrypoint")) s.entrypoint = val("f_entrypoint");
    if (val("f_instructions")) s.instructions = val("f_instructions");
    return s;
  }
  if (kind === "Prompt") {
    const s: Record<string, unknown> = { template: val("f_template") };
    const variables = val("f_variables")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, req, desc] = line.split("|").map((x) => x.trim());
        return { name, required: (req || "").toLowerCase() === "true", description: desc || null };
      })
      .filter((v) => v.name);
    if (variables.length) s.variables = variables;
    return s;
  }
  if (kind === "Secret") {
    const data: Record<string, string> = {};
    for (const line of val("f_data").split("\n")) {
      const idx = line.indexOf("=");
      if (idx > 0) data[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
    }
    return { data };
  }
  if (kind === "Deployment") {
    const s: Record<string, unknown> = {
      target_kind: val("f_target_kind"),
      target_namespace: val("f_target_namespace"),
      target_name: val("f_target_name"),
      cluster_namespace: val("f_cluster_namespace") || "default",
    };
    if (val("f_replicas")) s.replicas = Number(val("f_replicas"));
    return s;
  }
  return {};
}

interface DetailRow extends Omit<ResourceRow, "latest_version"> {
  latest_version: {
    tag: string | null;
    version: number;
    spec: Record<string, unknown>;
    change_notes: string | null;
  } | null;
  labels: Record<string, string>;
  status: { conditions?: { type: string; status: string; message?: string; reason?: string }[] };
  catalog: {
    title?: string;
    long_description?: string;
    keywords?: string[];
    authors?: string[];
    license?: string;
    links?: Record<string, string>;
  };
}

function DetailDialog({
  kind,
  namespace,
  name,
  onClose,
}: {
  kind: string;
  namespace: string;
  name: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [d, setD] = useState<DetailRow | null>(null);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<DetailRow>(`/v1/resources/${kind}/${namespace}/${name}`)
      .then(setD)
      .catch((e) => setError(String(e).replace("Error: ", "")));
    void api<VersionRow[]>(`/v1/resources/${kind}/${namespace}/${name}/versions`)
      .then(setVersions)
      .catch(() => {});
  }, [kind, namespace, name]);

  if (error) return <div className="overlay" onClick={onClose}><div className="dialog" onClick={(e) => e.stopPropagation()}><p className="error">{error}</p></div></div>;
  if (!d) return null;
  const cat = d.catalog || {};

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" style={{ width: 680 }} onClick={(e) => e.stopPropagation()}>
        <h3>
          {d.name}{" "}
          <span className={`badge ${d.visibility}`}>{t(`visibility.${d.visibility}`, d.visibility)}</span>
        </h3>
        {d.description && <p style={{ marginTop: 0 }}>{d.description}</p>}
        {(cat.keywords?.length || 0) > 0 && (
          <p>
            {cat.keywords!.map((k) => (
              <span key={k} className="badge gray" style={{ marginRight: 6 }}>{k}</span>
            ))}
          </p>
        )}
        {cat.long_description && (
          <>
            <label>{t("detail.longDescription")}</label>
            <pre style={{ whiteSpace: "pre-wrap", background: "var(--accent-soft)", padding: 12, borderRadius: 8 }}>{cat.long_description}</pre>
          </>
        )}
        <div className="grid2">
          {cat.authors?.length ? <p className="muted">{t("detail.authors")}: {cat.authors.join(", ")}</p> : null}
          {cat.license ? <p className="muted">{t("detail.license")}: {cat.license}</p> : null}
          {cat.links?.docs ? (
            <p className="muted">
              {t("detail.docs")}: <a href={cat.links.docs} target="_blank" rel="noreferrer">{cat.links.docs}</a>
            </p>
          ) : null}
        </div>
        {(d.status?.conditions?.length || 0) > 0 && (
          <>
            <label>{t("detail.status")}</label>
            {d.status!.conditions!.map((c, i) => (
              <p key={i} className="muted" style={{ margin: "4px 0" }}>
                <span className={`badge ${c.status === "True" ? "active" : "revoked"}`}>{c.type}: {c.status}</span>{" "}
                {c.message} {c.reason ? `(${c.reason})` : ""}
              </p>
            ))}
          </>
        )}
        {d.secret_keys && (
          <p className="muted">{t("detail.secretKeys")}: {d.secret_keys.join(", ")}</p>
        )}
        <label>{t("detail.spec")}</label>
        <pre style={{ maxHeight: 200, overflow: "auto", background: "var(--accent-soft)", padding: 12, borderRadius: 8, fontSize: 12 }}>
          {JSON.stringify(d.latest_version?.spec ?? {}, null, 2)}
        </pre>
        <label>{t("resources.versions")}</label>
        <table>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version}>
                <td style={{ whiteSpace: "nowrap" }}><strong>{v.tag || `v${v.version}`}</strong></td>
                <td>
                  {v.change_notes || <span className="muted">—</span>}
                  <div className="muted" style={{ fontSize: 12 }}>
                    {v.published_by} · {v.created_at.slice(0, 16).replace("T", " ")}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="actions">
          <button className="primary" onClick={onClose}>{t("common.ok")}</button>
        </div>
      </div>
    </div>
  );
}

export default function ResourceTab({ kind, namespace }: { kind: string; namespace: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [error, setError] = useState("");
  const [showPublish, setShowPublish] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [versions, setVersions] = useState<{ name: string; items: VersionRow[] } | null>(null);

  async function load() {
    try {
      const data = await api<{ items: ResourceRow[] }>(
        `/v1/resources?kind=${kind}&namespace=${namespace}&limit=200`
      );
      setRows(data.items);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }
  useEffect(() => {
    void load();
  }, [kind, namespace]);

  async function publish(form: FormData) {
    setError("");
    try {
      const body: Record<string, unknown> = {
        spec: buildSpec(kind, form),
        tag: String(form.get("tag") || "") || null,
        description: String(form.get("description") || "") || null,
        change_notes: String(form.get("change_notes") || "") || null,
      };
      if (kind !== "Prompt" && kind !== "Secret") {
        body.visibility = String(form.get("visibility"));
      }
      const catalog: Record<string, unknown> = {};
      const splitList = (k: string) =>
        String(form.get(k) || "")
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
      if (splitList("c_keywords").length) catalog.keywords = splitList("c_keywords");
      if (splitList("c_authors").length) catalog.authors = splitList("c_authors");
      if (String(form.get("c_license") || "").trim()) catalog.license = String(form.get("c_license")).trim();
      if (String(form.get("c_docs") || "").trim()) catalog.links = { docs: String(form.get("c_docs")).trim() };
      if (String(form.get("c_long") || "").trim()) catalog.long_description = String(form.get("c_long")).trim();
      if (Object.keys(catalog).length) body.catalog = catalog;
      const name = String(form.get("name"));
      await api(`/v1/resources/${kind}/${namespace}/${name}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setShowPublish(false);
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function remove(name: string) {
    if (!confirm(t("resources.confirmDelete", { name }))) return;
    try {
      await api(`/v1/resources/${kind}/${namespace}/${name}`, { method: "DELETE" });
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  async function showVersions(name: string) {
    try {
      const items = await api<VersionRow[]>(
        `/v1/resources/${kind}/${namespace}/${name}/versions`
      );
      setVersions({ name, items });
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  const fields = KIND_FIELDS[kind] || [];

  return (
    <div>
      <div style={{ display: "flex", marginBottom: 16 }}>
        <span style={{ flex: 1 }} />
        <button className="primary" onClick={() => setShowPublish(true)}>
          + {t("resources.publish")}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table>
          <thead>
            <tr>
              {["name", "visibility", "tag", "updated", ""].map((c) => (
                <th key={c}>{c ? t(`resources.cols.${c}`) : ""}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>
                  <strong>
                    <a href="#" style={{ color: "var(--accent)", textDecoration: "none" }}
                       onClick={(e) => { e.preventDefault(); setDetail(r.name); }}>
                      {r.name}
                    </a>
                  </strong>
                  {r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}
                </td>
                <td>
                  <span className={`badge ${r.visibility}`}>{t(`visibility.${r.visibility}`, r.visibility)}</span>
                </td>
                <td>{r.latest_version?.tag || (r.latest_version ? `v${r.latest_version.version}` : "-")}</td>
                <td className="muted">{r.updated_at.slice(0, 16).replace("T", " ")}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => void showVersions(r.name)}>
                    {t("resources.versions")}
                  </button>{" "}
                  <button className="danger" onClick={() => void remove(r.name)}>
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted" style={{ textAlign: "center", padding: 32 }}>
                  {t("resources.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showPublish && (
        <div className="overlay" onClick={() => setShowPublish(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>
              {t("resources.publish")} · {kind}
            </h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void publish(new FormData(e.currentTarget));
              }}
            >
              <label>{t("publish.name")}</label>
              <input name="name" required placeholder="payment-gateway" />
              <label>{t("publish.tag")}</label>
              <input name="tag" placeholder="v1.0.0" />
              {kind !== "Prompt" && kind !== "Secret" && (
                <>
                  <label>{t("publish.visibility")}</label>
                  <select name="visibility" defaultValue="internal">
                    <option value="internal">internal</option>
                    <option value="restricted">restricted</option>
                  </select>
                </>
              )}
              {kind === "Prompt" && <p className="muted">{t("resources.promptPrivate")}</p>}
              <label>{t("publish.description")}</label>
              <textarea name="description" rows={2} />
              {kind !== "Secret" && kind !== "Deployment" && (
                <>
                  <label>{t("fields.keywords")}</label>
                  <input name="c_keywords" placeholder="payment, mcp" />
                  <div className="grid2">
                    <div>
                      <label>{t("fields.authors")}</label>
                      <input name="c_authors" placeholder="alice" />
                    </div>
                    <div>
                      <label>{t("fields.license")}</label>
                      <input name="c_license" placeholder="Apache-2.0" />
                    </div>
                  </div>
                  <label>{t("fields.docs_link")}</label>
                  <input name="c_docs" placeholder="https://docs.example.com/gateway" />
                </>
              )}
              {kind === "Prompt" && (
                <>
                  <label>{t("fields.variables")}</label>
                  <textarea
                    name="f_variables"
                    rows={3}
                    placeholder={"concerns | true | \u91cd\u70b9\u5173\u6ce8\u7684\u98ce\u9669\u70b9\ncode | false | \u4ee3\u7801\u5185\u5bb9"}
                  />
                </>
              )}
              {fields.map((f) => (
                <div key={f.key}>
                  <label>{t(`fields.${f.labelKey}`)}</label>
                  {f.key === "transport" ? (
                    <select name="f_transport" defaultValue="streamable-http">
                      <option value="streamable-http">streamable-http</option>
                      <option value="sse">sse</option>
                      <option value="stdio">stdio</option>
                    </select>
                  ) : f.key === "target_kind" ? (
                    <select name="f_target_kind" defaultValue="Agent">
                      <option>Agent</option>
                      <option>MCPServer</option>
                    </select>
                  ) : f.key === "data" ? (
                    <textarea name="f_data" rows={4} placeholder={"API_KEY=xxx\nDB_URL=yyy"} />
                  ) : (
                    <input name={`f_${f.key}`} placeholder={f.placeholder} />
                  )}
                </div>
              ))}
              <label>{t("publish.changeNotes")}</label>
              <textarea name="change_notes" rows={2} placeholder={t("publish.changeNotesHint")} />
              <div className="actions">
                <button type="button" className="ghost" onClick={() => setShowPublish(false)}>
                  {t("common.cancel")}
                </button>
                <button className="primary">{t("publish.submit")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {detail && (
        <DetailDialog kind={kind} namespace={namespace} name={detail} onClose={() => setDetail(null)} />
      )}

      {versions && (
        <div className="overlay" onClick={() => setVersions(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>
              {t("resources.versions")} · {versions.name}
            </h3>
            <table>
              <tbody>
                {versions.items.map((v) => (
                  <tr key={v.version}>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <strong>{v.tag || `v${v.version}`}</strong>
                    </td>
                    <td>
                      {v.change_notes || <span className="muted">—</span>}
                      <div className="muted" style={{ fontSize: 12 }}>
                        {v.published_by} · {v.created_at.slice(0, 16).replace("T", " ")}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
