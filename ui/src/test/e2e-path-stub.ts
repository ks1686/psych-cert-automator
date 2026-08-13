/**
 * Browser / Vitest stand-in for `@tauri-apps/api/path`.
 *
 * `downloadDir()` is unavailable outside Tauri; tests pick a folder via the
 * dialog stub instead.
 */

export async function downloadDir(): Promise<string> {
  throw new Error("downloadDir is not available outside Tauri");
}
