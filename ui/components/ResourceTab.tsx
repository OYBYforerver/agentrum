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
    if (val("f_entrypoint")) s.entrypoint = val("f_entrypoint");
    if (val("f_instructions")) s.instructions = val("f_instructions");
    return s;
  }
  if (kind === "Prompt") return { template: val("f_template") };
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

export default function ResourceTab({ kind, namespace }: { kind: string; namespace: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ResourceRow[]>([]);
  const [error, setError] = useState("");
  const [showPublish, setShowPublish] = useState(false);
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
                  <strong>{r.name}</strong>
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
