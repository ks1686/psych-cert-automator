/**
 * Shared API client constants for the FastAPI sidecar.
 *
 * Use 127.0.0.1 (not "localhost"): on Windows "localhost" can resolve to ::1
 * (IPv6) first, but the backend binds 127.0.0.1 (IPv4) only.
 */

export const API_BASE = "http://127.0.0.1:8008";

export function pdfViewUrl(token: string): string {
  return `${API_BASE}/api/pdf?path=${encodeURIComponent(token)}`;
}
