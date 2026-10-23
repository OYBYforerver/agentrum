import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentrum",
  description: "Multi-tenant registry for AI agents, MCP servers, skills and prompts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
