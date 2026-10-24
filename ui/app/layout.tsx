import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentrum",
  description: "Multi-tenant registry for AI agents, MCP servers, skills and prompts",
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
