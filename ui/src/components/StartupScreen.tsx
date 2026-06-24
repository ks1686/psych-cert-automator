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

const TIMEOUT_MS = 30_000;
const MAX_RETRIES = 3;
/** How long the "Backend ready!" message stays visible before calling `onReady`. */
const READY_DISPLAY_MS = 1_500;
/** Poll interval for the elapsed-time counter (ms). */
const ELAPSED_TICK_MS = 200;

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
        subtext: "The Python backend did not respond within 30 seconds.",
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

  // Persisted refs that survive state resets on retry.
  const mountedRef = useRef(true);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const startTimeRef = useRef(Date.now());
  const unlistenFns = useRef<UnlistenFn[]>([]);
  const elapsedTimer = useRef<ReturnType<typeof setInterval>>(undefined);
  const timeoutTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const readyTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // ── cleanup helpers ────────────────────────────────────────────────────

  const clearAllTimers = useCallback(() => {
    if (elapsedTimer.current !== undefined) clearInterval(elapsedTimer.current);
    if (timeoutTimer.current !== undefined) clearTimeout(timeoutTimer.current);
    if (readyTimer.current !== undefined) clearTimeout(readyTimer.current);
  }, []);

  const removeAllListeners = useCallback(() => {
    for (const fn of unlistenFns.current) fn();
    unlistenFns.current = [];
  }, []);

  const fullCleanup = useCallback(() => {
    removeAllListeners();
    clearAllTimers();
  }, [removeAllListeners, clearAllTimers]);

  // ── sidecar event wiring ───────────────────────────────────────────────

  const wireEvents = useCallback(async () => {
    removeAllListeners();

    try {
      const unlistenReady = await listen("sidecar-ready", () => {
        if (!mountedRef.current) return;
        clearAllTimers();
        setState("ready");
        readyTimer.current = setTimeout(() => {
          if (!mountedRef.current) return;
          onReadyRef.current();
        }, READY_DISPLAY_MS);
      });
      unlistenFns.current.push(unlistenReady);

      const unlistenError = await listen<string>("sidecar-error", (event) => {
        if (!mountedRef.current) return;
        clearAllTimers();
        setState("error");
        setErrorMessage(tryParsePayload(event.payload));
      });
      unlistenFns.current.push(unlistenError);

      return true;
    } catch (err: unknown) {
      // Not running inside Tauri (e.g. `pnpm dev` in a plain browser).
      // Simulate a fast ready transition so the app is usable during dev.
      console.warn(
        "StartupScreen: Tauri event API unavailable (are you running outside Tauri?).",
        err instanceof Error ? err.message : err,
      );
      clearAllTimers();
      setState("ready");
      readyTimer.current = setTimeout(() => {
        if (!mountedRef.current) return;
        onReadyRef.current();
      }, READY_DISPLAY_MS);
      return false;
    }
  }, [removeAllListeners, clearAllTimers]);

  // ── retry ──────────────────────────────────────────────────────────────

  const handleRetry = useCallback(() => {
    if (retryCount >= MAX_RETRIES) return;

    const nextCount = retryCount + 1;
    setRetryCount(nextCount);
    setState("loading");
    setErrorMessage(null);
    setElapsed(0);
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

    // Emit a best-effort retry event so the Rust sidecar manager can react.
    void emit("retry-sidecar", { attempt: nextCount });
  }, [retryCount]);

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

    // Wire Tauri event listeners.
    void wireEvents();

    return () => {
      mountedRef.current = false;
      fullCleanup();
    };
    // wireEvents is intentionally excluded — restarting it on retries is
    // handled by handleRetry, not by re-running this effect.
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

          {/* Secondary detail */}
          {subtext && (
            <p className="text-xs text-muted-foreground">{subtext}</p>
          )}

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
