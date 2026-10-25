"use client";

import { useTranslation } from "react-i18next";
import { Bot, FileText, Server, Zap } from "lucide-react";
import ResourceTab from "./ResourceTab";

export const KINDS = [
  { kind: "MCPServer", icon: Server, key: "mcp" },
  { kind: "Agent", icon: Bot, key: "agents" },
  { kind: "Skill", icon: Zap, key: "skills" },
  { kind: "Prompt", icon: FileText, key: "prompts" },
] as const;

export type CatalogKind = (typeof KINDS)[number]["kind"];

/**
 * One catalog entry for all resource kinds: a segmented kind switcher on
 * top of the unchanged per-kind ResourceTab (kind-specific publish forms
 * and detail pages stay exactly as they were).
 */
export default function Catalog({
  project,
  kind,
  onKind,
}: {
  project: string;
  kind: CatalogKind;
  onKind: (kind: CatalogKind) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {KINDS.map((k) => {
          const Icon = k.icon;
          return (
            <button
              key={k.kind}
              className={kind === k.kind ? "primary" : "ghost"}
              onClick={() => onKind(k.kind)}
            >
              <Icon size={14} style={{ verticalAlign: -2 }} /> {t(`nav.kinds.${k.key}`)}
            </button>
          );
        })}
      </div>
      {/* keyed by kind: switching resets the tab's internal list/detail state */}
      <ResourceTab key={kind} kind={kind} namespace={project} />
    </div>
  );
}
