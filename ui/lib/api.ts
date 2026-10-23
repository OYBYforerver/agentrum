const TOKEN_KEY = "agentrum-token";
const SERVER_KEY = "agentrum-server";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getServer(): string {
  if (typeof window === "undefined") return "http://localhost:12122";
  const fromUrl = new URLSearchParams(window.location.search).get("server");
  return localStorage.getItem(SERVER_KEY) || fromUrl || window.location.origin.replace(":3000", ":12122");
}

export function setServer(server: string) {
  localStorage.setItem(SERVER_KEY, server.replace(/\/$/, ""));
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${getServer()}${path}`, { ...init, headers });
  if (resp.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    throw new Error("401 unauthorized");
  }
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      detail = (await resp.json()).detail || detail;
    } catch {
      /* keep status code */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
