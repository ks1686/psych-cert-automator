/**
 * Shared API client for the FastAPI sidecar.
 *
 * In a release build the Tauri shell starts the sidecar on a random free port
 * with a per-launch random token; a debug build (`bun run tauri dev`) uses
 * port 8008 and the token "psych-cert-dev". Both are exposed through the
 * `backend_config` command. Every request must send the token in the
 * X-Psych-Cert-Token header (or, for plain links, the `auth` query param).
 * Outside Tauri (Vite dev server, browser e2e, Vitest) the backend runs on the
 * fixed development port without a token.
 *
 * Use 127.0.0.1 (not "localhost"): on Windows "localhost" can resolve to ::1
 * (IPv6) first, but the backend binds 127.0.0.1 (IPv4) only.
 */

import { invoke, isTauri } from "@tauri-apps/api/core";

export const DEV_PORT = 8008;
export const TOKEN_HEADER = "X-Psych-Cert-Token";
const TOKEN_QUERY_PARAM = "auth";

interface BackendConfig {
  port: number;
  token: string;
}

let apiBase = `http://127.0.0.1:${DEV_PORT}`;
let apiToken = "";
let configPromise: Promise<void> | null = null;

/** Load the sidecar port and token from the Tauri shell (once per launch). */
export function initBackendConfig(): Promise<void> {
  if (!configPromise) {
    configPromise = (async () => {
      if (!isTauri()) return;
      const config = await invoke<BackendConfig>("backend_config");
      apiBase = `http://127.0.0.1:${config.port}`;
      apiToken = config.token;
    })().catch((error: unknown) => {
      configPromise = null;
      throw error;
    });
  }
  return configPromise;
}

/** Absolute URL for a backend path such as "/api/parse". */
export function apiUrl(path: string): string {
  return `${apiBase}${path}`;
}

/** fetch() against the sidecar, adding the launch token when there is one. */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  await initBackendConfig();
  if (!apiToken) return fetch(apiUrl(path), init);
  const headers = new Headers(init.headers);
  headers.set(TOKEN_HEADER, apiToken);
  return fetch(apiUrl(path), { ...init, headers });
}

export function pdfViewUrl(token: string): string {
  const auth = apiToken
    ? `&${TOKEN_QUERY_PARAM}=${encodeURIComponent(apiToken)}`
    : "";
  return `${apiUrl("/api/pdf")}?path=${encodeURIComponent(token)}${auth}`;
}
