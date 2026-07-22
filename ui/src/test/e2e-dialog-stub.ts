/**
 * Browser e2e stand-in for `@tauri-apps/plugin-dialog`.
 *
 * Vite aliases this module when `VITE_E2E=1` (and Vitest always aliases it).
 * Playwright seeds paths on `window.__E2E_PATHS__` before clicking Select.
 */

export interface E2eDialogPaths {
  zoom?: string;
  qualtrics?: string;
}

declare global {
  interface Window {
    __E2E_PATHS__?: E2eDialogPaths;
  }
}

interface OpenDialogOptions {
  title?: string;
  multiple?: boolean;
  filters?: Array<{ name: string; extensions: string[] }>;
}

function pathForTitle(title: string, paths: E2eDialogPaths): string | null {
  if (/zoom/i.test(title) && paths.zoom) return paths.zoom;
  if (/qualtrics/i.test(title) && paths.qualtrics) return paths.qualtrics;
  return paths.zoom ?? paths.qualtrics ?? null;
}

/** Matches the subset of `open` used by StepUpload. */
export async function open(
  options: OpenDialogOptions = {},
): Promise<string | string[] | null> {
  const paths = window.__E2E_PATHS__;
  if (!paths) return null;
  return pathForTitle(options.title ?? "", paths);
}
