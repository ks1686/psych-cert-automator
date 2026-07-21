import { useEffect, useState, useRef, useCallback } from "react";
import {
  listen,
  emit,
  type UnlistenFn,
} from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

interface StartupScreenProps {
  /** Called once the sidecar is confirmed ready (after brief success display). */
  onReady: () => void;
}

type StartupState = "loading" | "timeout" | "error" | "ready";

// ── Constants ────────────────────────────────────────────────────────────────

// Keep in sync with the Rust-side health-check timeout in src-tauri/src/lib.rs.
const TIMEOUT_MS = 60_000;
const MAX_RETRIES = 3;
/** Trailing sidecar stdout/stderr lines kept for the live log view. */
const MAX_LOG_LINES = 200;
/** How long the "Backend ready!" message stays visible before calling `onReady`. */
const READY_DISPLAY_MS = 1_500;
/** Poll interval for the elapsed-time counter (ms). */
const ELAPSED_TICK_MS = 200;
/**
 * Backend health endpoint. Use 127.0.0.1 (not "localhost"): on Windows,
 * "localhost" often resolves to ::1 (IPv6) first, but uvicorn binds
 * 127.0.0.1 (IPv4) only, so a localhost fetch can fail to connect.
 */
const HEALTH_URL = "http://127.0.0.1:8008/health";
/** How often the frontend polls the health endpoint (ms). */
const HEALTH_POLL_MS = 400;
/** Per-request abort timeout for a single health poll (ms). */
const HEALTH_REQ_TIMEOUT_MS = 2_000;

// ── Helpers ──────────────────────────────────────────────────────────────────

type StatusInfo = {
  headline: string;
  subtext?: string;
};

function deriveStatus(
  state: StartupState,
  elapsed: number,
  errorMessage: string | null,
): StatusInfo {
  switch (state) {
    case "error":
      return {
        headline: "Backend Error",
        subtext: errorMessage ?? "An unknown backend error occurred.",
      };
    case "timeout":
      return {
        headline: "Backend failed to start",
        subtext: "The Python backend did not respond within 60 seconds.",
      };
    case "ready":
      return {
        headline: "Backend ready!",
        subtext: "Loading application...",
      };
    case "loading": {
      if (elapsed < 5) return { headline: "Starting backend..." };
      if (elapsed < 15)
        return {
          headline: "Still starting... first launch may take a moment",
        };
      return { headline: "Backend is taking longer than expected..." };
    }
  }
}

/**
 * Convert raw Tauri event payload to a string.
 * The sidecar-error payload is emitted as a Rust `String`, which arrives as a
 * JSON string (i.e. `"like this"` with quotes).  `sidecar-ready` payload is
 * `serde_json::Value::Null`.
 */
function tryParsePayload(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload === null || payload === undefined) return "";
  try {
    return String(payload);
  } catch {
    return "Unknown payload";
  }
}

// ── Component ────────────────────────────────────────────────────────────────

export default function StartupScreen({ onReady }: StartupScreenProps) {
  const [state, setState] = useState<StartupState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [logLines, setLogLines] = useState<string[]>([]);

  // Persisted refs that survive state resets on retry.
  const mountedRef = useRef(true);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const startTimeRef = useRef(Date.now());
  const unlistenFns = useRef<UnlistenFn[]>([]);
  const elapsedTimer = useRef<ReturnType<typeof setInterval>>(undefined);
  const timeoutTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const readyTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pollTimer = useRef<ReturnType<typeof setInterval>>(undefined);
  const readyHandledRef = useRef(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  const appendLogLines = useCallback((chunk: string) => {
    const pieces = chunk.split("\n").filter((l) => l.length > 0);
    if (pieces.length === 0) return;
    setLogLines((prev) => [...prev, ...pieces].slice(-MAX_LOG_LINES));
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: "end" });
  }, [logLines]);

  // ── cleanup helpers ────────────────────────────────────────────────────

  const clearAllTimers = useCallback(() => {
    if (elapsedTimer.current !== undefined) clearInterval(elapsedTimer.current);
    if (timeoutTimer.current !== undefined) clearTimeout(timeoutTimer.current);
    if (readyTimer.current !== undefined) clearTimeout(readyTimer.current);
    if (pollTimer.current !== undefined) clearInterval(pollTimer.current);
  }, []);

  const removeAllListeners = useCallback(() => {
    for (const fn of unlistenFns.current) fn();
    unlistenFns.current = [];
  }, []);

  const fullCleanup = useCallback(() => {
    removeAllListeners();
    clearAllTimers();
  }, [removeAllListeners, clearAllTimers]);

  // ── readiness ──────────────────────────────────────────────────────────

  /**
   * Transition to the ready state exactly once. Both the direct health
   * poll and the (redundant) Tauri `sidecar-ready` event funnel through
   * here, so whichever fires first wins and the other is a no-op.
   */
  const markReady = useCallback(() => {
    if (readyHandledRef.current || !mountedRef.current) return;
    readyHandledRef.current = true;
    clearAllTimers();
    setState("ready");
    readyTimer.current = setTimeout(() => {
      if (!mountedRef.current) return;
      onReadyRef.current();
    }, READY_DISPLAY_MS);
  }, [clearAllTimers]);

  /**
   * Poll the backend health endpoint directly. This is the source of
   * truth for readiness — it does not depend on the fire-once
   * `sidecar-ready` Tauri event (which can be emitted before the webview
   * has registered its listener and thus be missed entirely), and it
   * verifies exactly what the app needs: that the backend is reachable
   * before any wizard step tries to call it.
   */
  const startHealthPolling = useCallback(() => {
    const tick = async () => {
      if (!mountedRef.current || readyHandledRef.current) return;
      try {
        const controller = new AbortController();
        const abort = setTimeout(
          () => controller.abort(),
          HEALTH_REQ_TIMEOUT_MS,
        );
        const res = await fetch(HEALTH_URL, { signal: controller.signal });
        clearTimeout(abort);
        if (res.ok) markReady();
      } catch {
        // Backend not reachable yet — keep polling until ready or timeout.
      }
    };
    void tick();
    pollTimer.current = setInterval(() => void tick(), HEALTH_POLL_MS);
  }, [markReady]);

  // ── sidecar event wiring (best-effort diagnostics only) ────────────────

  const wireEvents = useCallback(async () => {
    removeAllListeners();

    try {
      // Redundant fast path: if the event does arrive, use it.
      const unlistenReady = await listen("sidecar-ready", () => {
        markReady();
      });
      unlistenFns.current.push(unlistenReady);

      const unlistenError = await listen<string>("sidecar-error", (event) => {
        if (!mountedRef.current || readyHandledRef.current) return;
        clearAllTimers();
        setState("error");
        setErrorMessage(tryParsePayload(event.payload));
      });
      unlistenFns.current.push(unlistenError);

      const unlistenStdout = await listen<string>("sidecar-stdout", (event) => {
        if (!mountedRef.current) return;
        appendLogLines(tryParsePayload(event.payload));
      });
      unlistenFns.current.push(unlistenStdout);

      const unlistenStderr = await listen<string>("sidecar-stderr", (event) => {
        if (!mountedRef.current) return;
        appendLogLines(tryParsePayload(event.payload));
      });
      unlistenFns.current.push(unlistenStderr);
    } catch (err: unknown) {
      // Not running inside Tauri (e.g. `bun run dev` in a plain browser).
      // That's fine — health polling is independent of Tauri events and
      // remains the source of truth for readiness.
      console.warn(
        "StartupScreen: Tauri event API unavailable (running outside Tauri?). " +
          "Falling back to direct health polling.",
        err instanceof Error ? err.message : err,
      );
    }
  }, [removeAllListeners, clearAllTimers, appendLogLines, markReady]);

  // ── retry ──────────────────────────────────────────────────────────────

  const handleRetry = useCallback(() => {
    if (retryCount >= MAX_RETRIES) return;

    const nextCount = retryCount + 1;
    setRetryCount(nextCount);
    setState("loading");
    setErrorMessage(null);
    setElapsed(0);
    readyHandledRef.current = false;
    startTimeRef.current = Date.now();

    // Restart elapsed counter.
    elapsedTimer.current = setInterval(() => {
      if (!mountedRef.current) return;
      setElapsed(
        Math.floor((Date.now() - startTimeRef.current) / 1000),
      );
    }, ELAPSED_TICK_MS);

    // Restart timeout.
    timeoutTimer.current = setTimeout(() => {
      if (!mountedRef.current) return;
      setState("timeout");
    }, TIMEOUT_MS);

    // Resume polling the backend health endpoint.
    startHealthPolling();

    // Emit a best-effort retry event so the Rust sidecar manager can react.
    void emit("retry-sidecar", { attempt: nextCount });
  }, [retryCount, startHealthPolling]);

  // ── quit ───────────────────────────────────────────────────────────────

  const handleQuit = useCallback(async () => {
    try {
      await getCurrentWindow().close();
    } catch (err: unknown) {
      // Not running in Tauri — show a message instead.
      console.warn(
        "StartupScreen: cannot close window outside Tauri.",
        err instanceof Error ? err.message : err,
      );
      setErrorMessage(
        "Close this browser tab to exit (not running in Tauri).",
      );
      setState("error");
    }
  }, []);

  // ── mount / unmount ────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true;

    // Set up elapsed counter.
    startTimeRef.current = Date.now();
    elapsedTimer.current = setInterval(() => {
      if (!mountedRef.current) return;
      setElapsed(
        Math.floor((Date.now() - startTimeRef.current) / 1000),
      );
    }, ELAPSED_TICK_MS);

    // Set up timeout.
    timeoutTimer.current = setTimeout(() => {
      if (!mountedRef.current) return;
      setState("timeout");
    }, TIMEOUT_MS);

    // Wire Tauri event listeners (best-effort diagnostics), then start the
    // direct health poll that actually drives readiness.
    void wireEvents();
    startHealthPolling();

    return () => {
      mountedRef.current = false;
      fullCleanup();
    };
    // wireEvents/startHealthPolling are intentionally excluded — restarting
    // them on retries is handled by handleRetry, not by re-running this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── derived display values ─────────────────────────────────────────────

  const { headline, subtext } = deriveStatus(state, elapsed, errorMessage);

  const isFailure = state === "timeout" || state === "error";
  const canRetry = retryCount < MAX_RETRIES && isFailure;
  const retryLabel = canRetry
    ? "Retry"
    : `Retried ${retryCount}/${MAX_RETRIES}`;

  // Icon displayed in the branding circle.
  const StatusIcon = (() => {
    if (state === "ready") return CheckCircle2;
    if (isFailure) return AlertTriangle;
    return Loader2;
  })();

  // ── render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center pb-2">
          <div
            className={cn(
              "mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl transition-colors",
              isFailure
                ? "bg-destructive/10"
                : state === "ready"
                  ? "bg-primary/10"
                  : "bg-primary/10",
            )}
          >
            <StatusIcon
              className={cn(
                "h-8 w-8",
                isFailure
                  ? "text-destructive"
                  : state === "ready"
                    ? "text-primary"
                    : "text-primary animate-spin",
              )}
            />
          </div>

          <CardTitle className="text-2xl font-bold tracking-tight">
            Psych Cert Gen
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">Rutgers GSAPP</p>
        </CardHeader>

        <CardContent className="space-y-3 pt-4 text-center">
          {/* Primary status */}
          <p
            className={cn(
              "text-sm font-medium",
              isFailure
                ? "text-destructive"
                : state === "ready"
                  ? "text-primary"
                  : "text-foreground",
            )}
          >
            {headline}
          </p>

          {/* Secondary detail — errors may carry a multi-line stderr tail,
              so render those left-aligned, monospace, and scrollable rather
              than as centered prose. */}
          {subtext &&
            (state === "error" ? (
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-2 text-left font-mono text-xs text-muted-foreground">
                {subtext}
              </pre>
            ) : (
              <p className="text-xs text-muted-foreground">{subtext}</p>
            ))}

          {/* Platform note — only during loading */}
          {state === "loading" && (
            <p className="text-xs text-muted-foreground/70">
              First launch may take a few seconds while the backend initializes
            </p>
          )}

          {/* Elapsed-time counter — only during loading */}
          {state === "loading" && (
            <p className="text-xs tabular-nums text-muted-foreground">
              {elapsed}s elapsed
            </p>
          )}

          {/* Live sidecar stdout/stderr — lets you watch what the backend
              process is actually doing without needing devtools. */}
          {logLines.length > 0 && (
            <div className="max-h-48 overflow-y-auto rounded-md bg-muted/50 p-2 text-left">
              <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-muted-foreground">
                {logLines.join("\n")}
              </pre>
              <div ref={logEndRef} />
            </div>
          )}

          {/* Failure actions */}
          {isFailure && (
            <div className="flex items-center justify-center gap-3 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleRetry}
                disabled={!canRetry}
              >
                {retryLabel}
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => void handleQuit()}
              >
                Quit
              </Button>
            </div>
          )}

          {/* Ready transition indicator */}
          {state === "ready" && (
            <div className="flex items-center justify-center gap-2 pt-2">
              <div className="h-2 w-2 animate-pulse rounded-full bg-primary" />
              <span className="text-xs text-muted-foreground">
                Redirecting…
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
