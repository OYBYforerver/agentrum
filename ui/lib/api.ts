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
  // URL parameter wins over a stale localStorage value (same precedence as ?token=).
  const fromUrl = new URLSearchParams(window.location.search).get("server");
  return (
    fromUrl ||
    localStorage.getItem(SERVER_KEY) ||
    window.location.origin.replace(":3000", ":12122")
  );
}

export function setServer(server: string) {
  const trimmed = server.trim().replace(/\/$/, "");
  if (!trimmed) return;
  localStorage.setItem(SERVER_KEY, trimmed);
}

/** Normalize an unknown error into a human-readable message (no "Error: " prefix). */
export function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e).replace(/^Error: /, "");
}

/** Run an async action under a busy flag; errors go to onError (never swallowed silently). */
export async function withBusy(
  setBusy: (busy: boolean) => void,
  fn: () => Promise<void>,
  onError?: (e: unknown) => void
) {
  setBusy(true);
  try {
    await fn();
  } catch (e) {
    if (onError) onError(e);
    else throw e;
  } finally {
    setBusy(false);
  }
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
