import { afterEach, beforeEach, expect, test, vi } from "vitest";

const invokeMock = vi.fn();
const isTauriMock = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  isTauri: () => isTauriMock(),
}));

beforeEach(() => {
  vi.resetModules();
  invokeMock.mockReset();
  isTauriMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("desktop app uses the per-launch port and token", async () => {
  isTauriMock.mockReturnValue(true);
  invokeMock.mockResolvedValue({ port: 51234, token: "abc123" });
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./client");
  await client.apiFetch("/api/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  expect(invokeMock).toHaveBeenCalledWith("backend_config");
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("http://127.0.0.1:51234/api/parse");
  const headers = new Headers(init.headers);
  expect(headers.get("X-Psych-Cert-Token")).toBe("abc123");
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(client.pdfViewUrl("tok en")).toBe(
    "http://127.0.0.1:51234/api/pdf?path=tok%20en",
  );
});

test("browser dev mode keeps the fixed port and sends no token", async () => {
  isTauriMock.mockReturnValue(false);
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);

  const client = await import("./client");
  await client.apiFetch("/health");

  expect(invokeMock).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8008/health", {});
  expect(client.pdfViewUrl("x")).toBe("http://127.0.0.1:8008/api/pdf?path=x");
});
