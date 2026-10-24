"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, History, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";

interface ResourceRow {
  kind: string;
  namespace: string;
  name: string;
  visibility: string;
  description: string | null;
  catalog: {
    keywords?: string[];
    authors?: string[];
    license?: string;
    links?: Record<string, string>;
    long_description?: string;
  };
  labels: Record<string, string>;
  status: { conditions?: { type: string; status: string; message?: string; reason?: string }[] };
  secret_keys: string[] | null;
  updated_at: string;
  latest_version: {
    tag: string | null;
    version: number;
    spec: Record<string, unknown>;
    change_notes: string | null;
  } | null;
}

interface VersionRow {
  version: number;
  tag: string | null;
  spec: Record<string, unknown>;
  change_notes: string | null;
  published_by: string;
  created_at: string;
}

interface DetailRow extends ResourceRow {
  latest_version: ResourceRow["latest_version"];
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

function val(form: FormData, k: string) {
  return String(form.get(k) || "").trim();
}

function buildSpec(kind: string, form: FormData): Record<string, unknown> {
  if (kind === "Secret") {
    const data: Record<string, string> = {};
    for (const line of val(form, "f_data").split("\n")) {
      const idx = line.indexOf("=");
      if (idx > 0) data[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
    }
    return { data };
  }
  if (kind === "Deployment") {
    const s: Record<string, unknown> = {
      target_kind: val(form, "f_target_kind") || "Agent",
      target_namespace: val(form, "f_target_namespace"),
      target_name: val(form, "f_target_name"),
      cluster_namespace: val(form, "f_cluster_namespace") || "default",
    };
    if (val(form, "f_replicas")) s.replicas = Number(val(form, "f_replicas"));
    return s;
  }
  if (kind === "Agent") {
    const s: Record<string, unknown> = { image: val(form, "f_image") };
    if (val(form, "f_framework")) s.framework = val(form, "f_framework");
    return s;
  }
  if (kind === "MCPServer") {
    const s: Record<string, unknown> = { transport: val(form, "f_transport") || "streamable-http" };
    if (val(form, "f_endpoint")) s.endpoint = val(form, "f_endpoint");
    if (val(form, "f_command")) s.command = val(form, "f_command");
    return s;
  }
  if (kind === "Skill") {
    const s: Record<string, unknown> = {};
    if (val(form, "f_source_url")) {
      const git: Record<string, unknown> = { url: val(form, "f_source_url") };
      if (val(form, "f_source_ref")) git.ref = val(form, "f_source_ref");
      if (val(form, "f_source_subdirectory")) git.subdirectory = val(form, "f_source_subdirectory");
      if (val(form, "f_source_credentials_ref")) git.credentials_ref = val(form, "f_source_credentials_ref");
      s.source = { git };
    }
    if (val(form, "f_entrypoint")) s.entrypoint = val(form, "f_entrypoint");
    if (val(form, "f_instructions")) s.instructions = val(form, "f_instructions");
    return s;
  }
  if (kind === "Prompt") {
    const s: Record<string, unknown> = { template: val(form, "f_template") };
    const variables = val(form, "f_variables")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, req, desc] = line.split("|").map((x) => x.trim());
        return { name, required: (req || "").toLowerCase() === "true", description: desc || null };
      })
      .filter((v) => v.name);
    if (variables.length) s.variables = variables;
    return s;
  }
  return {};
}

function CopyBtn({ text, label }: { text: string; label?: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  return (
    <button
      className="ghost copy-btn"
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1200);
      }}
    >
      <Copy size={13} /> {done ? t("detail.copied") : label || t("detail.copy")}
    </button>
  );
}

/** Per-kind key column: each type shows what matters to it. */
function KeyCell({ r, onOpen }: { r: ResourceRow; onOpen: (name: string) => void }) {
  const { t } = useTranslation();
  const open = (e: { preventDefault: () => void }) => {
    e.preventDefault();
    onOpen(r.name);
  };
  const spec = (r.latest_version?.spec || {}) as Record<string, unknown>;
  if (r.kind === "MCPServer") {
    const ep = String(spec.endpoint || spec.command || "");
    return (
      <td>
        <strong>
          <a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>
            {r.name}
          </a>
        </strong>
        {r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}
        {ep && <div className="muted mono" style={{ fontSize: 12 }}>{ep.slice(0, 46)}</div>}
      </td>
    );
  }
  if (r.kind === "Agent") {
    return (
      <td>
        <strong><a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>{r.name}</a></strong>
        {r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}
        {spec.image ? <div className="muted mono" style={{ fontSize: 12 }}>{String(spec.image).slice(0, 46)}</div> : null}
      </td>
    );
  }
  if (r.kind === "Skill") {
    const git = ((spec.source || {}) as Record<string, unknown>).git as Record<string, unknown> | undefined;
    const drift = (r.status?.conditions || []).find((c) => c.type === "UpstreamDrift");
    return (
      <td>
        <strong><a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>{r.name}</a></strong>
        {git ? (
          <div className="muted mono" style={{ fontSize: 12 }}>
            {String(git.ref)}@{String(git.resolved_sha || "").slice(0, 8)}
            {drift && drift.status === "True" && (
              <span className="badge restricted" style={{ marginLeft: 6 }}>drift</span>
            )}
          </div>
        ) : r.description ? (
          <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>
        ) : null}
      </td>
    );
  }
  if (r.kind === "Prompt") {
    const vars = (spec.variables || []) as unknown[];
    return (
      <td>
        <strong><a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>{r.name}</a></strong>
        {r.description && <div className="muted" style={{ fontSize: 12 }}>{r.description}</div>}
        <div className="muted" style={{ fontSize: 12 }}>
          {t("resources.varCount", { count: vars.length })}
        </div>
      </td>
    );
  }
  if (r.kind === "Secret") {
    return (
      <td>
        <strong><a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>{r.name}</a></strong>
        <div className="muted" style={{ fontSize: 12 }}>
          {t("resources.keys", { count: (r.secret_keys || []).length })}
        </div>
      </td>
    );
  }
  if (r.kind === "Deployment") {
    return (
      <td>
        <strong><a href="#" style={{ color: "var(--accent)", textDecoration: "none" }} onClick={open}>{r.name}</a></strong>
        <div className="muted mono" style={{ fontSize: 12 }}>
          {String(spec.target_kind || "")} {String(spec.target_namespace || "")}/{String(spec.target_name || "")} → {String(spec.cluster_namespace || "")}
        </div>
      </td>
    );
  }
  return <td><strong>{r.name}</strong></td>;
}

function secondaryCol(r: ResourceRow): string {
  const spec = (r.latest_version?.spec || {}) as Record<string, unknown>;
  if (r.kind === "Agent") return String(spec.framework || "");
  if (r.kind === "Prompt") return String(spec.template || "").slice(0, 40);
  if (r.kind === "Deployment") return `replicas ${spec.replicas ?? 1}`;
  return "";
}

export default function ResourceTab({ kind, namespace }: { kind: string; namespace: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [error, setError] = useState("");
  const [showPublish, setShowPublish] = useState(false);
  const [prefill, setPrefill] = useState<Record<string, unknown> | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [edit, setEdit] = useState<ResourceRow | null>(null);
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
        tag: val(form, "tag") || null,
        description: val(form, "description") || null,
        change_notes: val(form, "change_notes") || null,
      };
      if (kind !== "Prompt" && kind !== "Secret") body.visibility = val(form, "visibility");
      const catalog: Record<string, unknown> = {};
      const splitList = (k: string) => val(form, k).split(",").map((x) => x.trim()).filter(Boolean);
      if (splitList("c_keywords").length) catalog.keywords = splitList("c_keywords");
      if (splitList("c_authors").length) catalog.authors = splitList("c_authors");
      if (val(form, "c_license")) catalog.license = val(form, "c_license");
      if (val(form, "c_docs")) catalog.links = { docs: val(form, "c_docs") };
      if (val(form, "c_long")) catalog.long_description = val(form, "c_long");
      if (Object.keys(catalog).length) body.catalog = catalog;
      const name = val(form, "name");
      await api(`/v1/resources/${kind}/${namespace}/${name}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setShowPublish(false);
      setPrefill(null);
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  /** 元数据编辑:PATCH,不产生版本(spec/tag 不可变) */
  async function saveEdit(form: FormData, r: ResourceRow) {
    setError("");
    try {
      const body: Record<string, unknown> = {
        description: val(form, "e_description"),
        visibility: val(form, "e_visibility"),
        catalog: {},
      };
      const splitList = (k: string) => val(form, k).split(",").map((x) => x.trim()).filter(Boolean);
      if (splitList("e_keywords").length) (body.catalog as Record<string, unknown>).keywords = splitList("e_keywords");
      if (val(form, "e_license")) (body.catalog as Record<string, unknown>).license = val(form, "e_license");
      if (val(form, "e_long")) (body.catalog as Record<string, unknown>).long_description = val(form, "e_long");
      await api(`/v1/resources/${r.kind}/${r.namespace}/${r.name}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setEdit(null);
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  /** 删除:带影响面提示 */
  async function remove(r: ResourceRow) {
    setError("");
    let impact = 0;
    try {
      const consumers = await api<{ subscriber_team: string; kind: string; name: string }[]>(
        `/v1/teams/${namespace}/consumers`
      );
      impact = consumers.filter((c) => c.kind === r.kind && c.name === r.name).length;
    } catch {
      /* 无权限时退回普通确认 */
    }
    const msg = impact
      ? t("resources.confirmDeleteImpact", { name: r.name, count: impact })
      : t("resources.confirmDelete", { name: r.name });
    if (!confirm(msg)) return;
    try {
      await api(`/v1/resources/${r.kind}/${r.namespace}/${r.name}`, { method: "DELETE" });
      void load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    }
  }

  /** 发布新版本:预填上一版 spec */
  async function newVersion(r: ResourceRow) {
    setPrefill(r.latest_version?.spec || {});
    setShowPublish(true);
    setTimeout(() => {
      const form = document.querySelector(".dialog form") as HTMLFormElement | null;
      if (!form) return;
      const spec = r.latest_version?.spec || {};
      const set = (name: string, v: unknown) => {
        const el = form.elements.namedItem(name) as HTMLInputElement | null;
        if (el && v != null) el.value = String(v);
      };
      set("name", r.name);
      set("description", r.description);
      if (kind === "Agent") {
        set("f_image", spec.image);
        set("f_framework", spec.framework);
      } else if (kind === "MCPServer") {
        set("f_transport", spec.transport);
        set("f_endpoint", spec.endpoint);
        set("f_command", spec.command);
      } else if (kind === "Skill") {
        const git = ((spec.source || {}) as Record<string, unknown>).git as Record<string, unknown> | undefined;
        if (git) {
          set("f_source_url", git.url);
          set("f_source_ref", git.ref === "HEAD" ? "" : git.ref);
          set("f_source_subdirectory", git.subdirectory);
          set("f_source_credentials_ref", git.credentials_ref);
        }
        set("f_entrypoint", spec.entrypoint);
        set("f_instructions", spec.instructions);
      } else if (kind === "Prompt") {
        set("f_template", spec.template);
        set(
          "f_variables",
          ((spec.variables || []) as { name: string; required: boolean; description: string }[])
            .map((v) => `${v.name} | ${v.required} | ${v.description || ""}`)
            .join("\n")
        );
      } else if (kind === "Deployment") {
        set("f_target_kind", spec.target_kind);
        set("f_target_namespace", spec.target_namespace);
        set("f_target_name", spec.target_name);
        set("f_cluster_namespace", spec.cluster_namespace);
        set("f_replicas", spec.replicas);
      }
      (form.elements.namedItem("change_notes") as HTMLTextAreaElement | null)?.focus();
    }, 100);
  }

  const fields = KIND_FIELDS[kind] || [];

  return (
    <div>
      <div style={{ display: "flex", marginBottom: 16 }}>
        <span style={{ flex: 1 }} />
        <button className="primary" onClick={() => { setPrefill(null); setShowPublish(true); }}>
          <Plus size={14} style={{ verticalAlign: -2 }} /> {t("resources.publish")}
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
                <KeyCell r={r} onOpen={setDetail} />
                <td>
                  <span className={`badge ${r.visibility}`}>{t(`visibility.${r.visibility}`, r.visibility)}</span>
                </td>
                <td>{r.latest_version?.tag || (r.latest_version ? `v${r.latest_version.version}` : "-")}</td>
                <td className="muted">{r.updated_at.slice(0, 16).replace("T", " ")}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost icon-btn" title={t("resources.newVersion")} onClick={() => void newVersion(r)}>
                    <Plus size={14} />
                  </button>{" "}
                  <button className="ghost icon-btn" title={t("resources.editMeta")} onClick={() => setEdit(r)}>
                    <Pencil size={14} />
                  </button>{" "}
                  <button
                    className="ghost icon-btn"
                    title={t("resources.versions")}
                    onClick={() => {
                      void api<VersionRow[]>(`/v1/resources/${r.kind}/${r.namespace}/${r.name}/versions`)
                        .then((items) => setVersions({ name: r.name, items }))
                        .catch((e) => setError(String(e).replace("Error: ", "")));
                    }}
                  >
                    <History size={14} />
                  </button>{" "}
                  <button className="danger icon-btn" title={t("common.delete")} onClick={() => void remove(r)}>
                    <Trash2 size={14} />
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
        <div className="overlay" onClick={() => { setShowPublish(false); setPrefill(null); }}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{prefill ? t("resources.newVersion") : t("resources.publish")} · {kind}</h3>
            {prefill && <p className="muted" style={{ marginTop: -8 }}>{t("resources.prefillHint")}</p>}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void publish(new FormData(e.currentTarget));
              }}
            >
              <label>{t("publish.name")}</label>
              <input name="name" required />
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
                <button type="button" className="ghost" onClick={() => { setShowPublish(false); setPrefill(null); }}>
                  {t("common.cancel")}
                </button>
                <button className="primary">{t("publish.submit")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {edit && (
        <div className="overlay" onClick={() => setEdit(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("resources.editMeta")} · {edit.name}</h3>
            <p className="muted" style={{ marginTop: -8 }}>{t("resources.editMetaHint")}</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void saveEdit(new FormData(e.currentTarget), edit);
              }}
            >
              <label>{t("publish.description")}</label>
              <textarea name="e_description" rows={2} defaultValue={edit.description || ""} />
              {edit.kind !== "Prompt" && (
                <>
                  <label>{t("publish.visibility")}</label>
                  <select name="e_visibility" defaultValue={edit.visibility}>
                    <option value="internal">internal</option>
                    <option value="restricted">restricted</option>
                  </select>
                </>
              )}
              <label>{t("fields.keywords")}</label>
              <input name="e_keywords" defaultValue={((edit.catalog?.keywords) || []).join(", ")} />
              <label>{t("fields.license")}</label>
              <input name="e_license" defaultValue={edit.catalog?.license || ""} />
              <label>{t("fields.long_description")}</label>
              <textarea name="e_long" rows={4} defaultValue={edit.catalog?.long_description || ""} />
              <div className="actions">
                <button type="button" className="ghost" onClick={() => setEdit(null)}>
                  {t("common.cancel")}
                </button>
                <button className="primary">{t("common.ok")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {detail && <DetailDialog kind={kind} namespace={namespace} name={detail} onClose={() => setDetail(null)} />}

      {versions && (
        <div className="overlay" onClick={() => setVersions(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{t("resources.versions")} · {versions.name}</h3>
            <table>
              <tbody>
                {versions.items.map((v) => (
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
          </div>
        </div>
      )}
    </div>
  );
}

/** Per-kind identity page: the detail dialog speaks each type's language. */
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
  const [vars, setVars] = useState<Record<string, string>>({});

  useEffect(() => {
    void api<DetailRow>(`/v1/resources/${kind}/${namespace}/${name}`)
      .then(setD)
      .catch((e) => setError(String(e).replace("Error: ", "")));
    void api<VersionRow[]>(`/v1/resources/${kind}/${namespace}/${name}/versions`)
      .then(setVersions)
      .catch(() => {});
  }, [kind, namespace, name]);

  if (error)
    return (
      <div className="overlay" onClick={onClose}>
        <div className="dialog" onClick={(e) => e.stopPropagation()}><p className="error">{error}</p></div>
      </div>
    );
  if (!d) return null;
  const cat = d.catalog || {};
  const spec = (d.latest_version?.spec || {}) as Record<string, unknown>;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog" style={{ width: 700 }} onClick={(e) => e.stopPropagation()}>
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
            <pre className="pre-soft">{cat.long_description}</pre>
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

        {kind === "MCPServer" && Boolean(spec.endpoint) && (
          <>
            <label>{t("detail.endpoint")}</label>
            <div className="snippet-row">
              <pre className="pre-soft mono" style={{ flex: 1, margin: 0 }}>{String(spec.endpoint)}</pre>
              <CopyBtn text={String(spec.endpoint)} />
            </div>
            <label>{t("detail.cursorConfig")}</label>
            <div className="snippet-row">
              <pre className="pre-soft mono" style={{ flex: 1, margin: 0 }}>
                {JSON.stringify({ mcpServers: { [d.name]: { url: String(spec.endpoint) } } }, null, 2)}
              </pre>
              <CopyBtn text={JSON.stringify({ mcpServers: { [d.name]: { url: String(spec.endpoint) } } }, null, 2)} />
            </div>
          </>
        )}

        {kind === "Agent" && Boolean(spec.image) && (
          <>
            <label>{t("detail.pullCommand")}</label>
            <div className="snippet-row">
              <pre className="pre-soft mono" style={{ flex: 1, margin: 0 }}>docker pull {String(spec.image)}</pre>
              <CopyBtn text={`docker pull ${String(spec.image)}`} />
            </div>
            {(spec.env as unknown[] | undefined)?.length ? (
              <p className="muted">{t("detail.envVars")}: {(spec.env as { name: string }[]).map((e) => e.name).join(", ")}</p>
            ) : null}
          </>
        )}

        {kind === "Skill" && Boolean((spec.source as { git?: Record<string, unknown> } | undefined)?.git) && (
          (() => {
            const git = (spec.source as { git: Record<string, unknown> }).git;
            const drift = (d.status?.conditions || []).find((c) => c.type === "UpstreamDrift");
            return (
              <>
                <label>{t("detail.gitSource")}</label>
                <div className="snippet-row">
                  <pre className="pre-soft mono" style={{ flex: 1, margin: 0 }}>
                    {String(git.url)} @ {String(git.ref)} ({String(git.resolved_sha || "").slice(0, 10)})
                  </pre>
                  <CopyBtn text={`git clone ${String(git.url)}`} label={t("detail.clone")} />
                </div>
                {drift && (
                  <p style={{ margin: "8px 0" }}>
                    <span className={`badge ${drift.status === "True" ? "restricted" : "active"}`}>
                      UpstreamDrift: {drift.status}
                    </span>{" "}
                    <span className="muted">{String(drift.message)}</span>
                  </p>
                )}
              </>
            );
          })()
        )}

        {kind === "Prompt" && (
          <>
            <label>{t("detail.previewTitle")}</label>
            {((spec.variables || []) as { name: string; required: boolean; description: string }[]).map((v) => (
              <div key={v.name} style={{ marginBottom: 6 }}>
                <input
                  style={{ width: "100%" }}
                  placeholder={`${v.name}${v.required ? " *" : ""}${v.description ? " — " + v.description : ""}`}
                  onChange={(e) => setVars((old) => ({ ...old, [v.name]: e.target.value }))}
                />
              </div>
            ))}
            <pre className="pre-soft" style={{ whiteSpace: "pre-wrap" }}>
              {String(spec.template || "").replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k: string) => vars[k] || `{{${k}}}`)}
            </pre>
            <div className="snippet-row" style={{ marginBottom: 10 }}>
              <CopyBtn text={String(spec.template || "")} label={t("detail.copyTemplate")} />
            </div>
          </>
        )}

        {d.secret_keys && <p className="muted">{t("detail.secretKeys")}: {d.secret_keys.join(", ")}</p>}

        {(d.status?.conditions?.length || 0) > 0 && kind !== "Skill" && (
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

        <label>{t("detail.spec")}</label>
        <pre className="pre-soft mono" style={{ maxHeight: 180, overflow: "auto", fontSize: 12 }}>
          {JSON.stringify(spec, null, 2)}
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
