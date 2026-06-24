import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
  Component,
} from "react";
import { listen } from "@tauri-apps/api/event";
import { Loader2, AlertCircle } from "lucide-react";
import { Toaster, toast } from "sonner";

import { Button } from "@/components/ui/button";
import StepMetadata from "@/components/StepMetadata";
import type { MetadataFormData } from "@/components/StepMetadata";
import StepUpload from "@/components/StepUpload";
import type { UploadData } from "@/components/StepUpload";
import StepMatchReview from "@/components/StepMatchReview";
import type {
  MatchData,
  MatchEntryWire,
  ParticipantSummary,
  CERequestSummary,
} from "@/components/StepMatchReview";
import StepGenerate from "@/components/StepGenerate";
import type { TrainingMetadata } from "@/components/StepGenerate";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type WizardStep = 1 | 2 | 3 | 4;

export interface WizardState {
  metadata: MetadataFormData | null;
  uploadData: UploadData | null;
  matchData: MatchData | null;
  trainingMetadata: TrainingMetadata | null;
}

export interface WizardContextValue {
  /** Current wizard step (1–4) */
  step: WizardStep;
  /** All accumulated wizard data — null until its step has been completed */
  state: WizardState;
}

type TransitionPhase = "idle" | "matching";

// ─────────────────────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────────────────────

const WizardContext = createContext<WizardContextValue | null>(null);

/**
 * Hook to access the wizard state from any descendant component.
 * Must be called inside the <WizardContext.Provider> rendered by App.
 */
export function useWizard(): WizardContextValue {
  const ctx = useContext(WizardContext);
  if (!ctx) {
    throw new Error("useWizard must be used within a WizardProvider");
  }
  return ctx;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8008";

/** Derive TrainingMetadata from Step 1 + Step 2 data. */
function deriveTrainingMetadata(
  metadata: MetadataFormData,
  uploadData: UploadData,
): TrainingMetadata {
  const ceTypes: string[] = [];
  if (metadata.ceTypes.apa) ceTypes.push("APA");
  if (metadata.ceTypes.nasp) ceTypes.push("NASP");
  if (metadata.ceTypes.bcba) ceTypes.push("BCBA");

  return {
    title: metadata.title,
    date: metadata.date,
    instructor_name: metadata.instructor,
    ce_credits: metadata.ceCredits,
    ce_types_offered: ceTypes,
    session_start: uploadData.sessionStart,
    session_end: uploadData.sessionEnd,
  };
}

/** Convert StepUpload's internal participant type → MatchReview wire type. */
function toParticipantSummary(
  p: UploadData["zoomParticipants"][number],
): ParticipantSummary {
  return {
    name: p.name_raw,
    first_join: p.first_join,
    last_leave: p.last_leave,
    total_attended_minutes: p.total_attended_minutes,
    segments_count: p.segment_count,
  };
}

/** Convert StepUpload's internal CE request type → MatchReview wire type. */
function toCERequestSummary(
  r: UploadData["ceRequests"][number],
): CERequestSummary {
  return {
    name_on_certificate: r.name_on_certificate,
    email: r.email,
    ce_type: r.ce_type,
    license_number: r.license_number,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

/** Shown while waiting for the Tauri sidecar to be ready. */
function LoadingScreen() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <h1 className="text-2xl font-bold tracking-tight">Psych Cert Gen</h1>
      <p className="text-muted-foreground">Starting Psych Cert Gen...</p>
    </main>
  );
}

/** Rendered by the AppErrorBoundary when an unhandled error is caught. */
function ErrorFallback({
  error,
  onReset,
}: {
  error: Error | null;
  onReset: () => void;
}) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <AlertCircle className="h-12 w-12 text-destructive" />
      <div className="text-center">
        <h1 className="text-2xl font-bold">Something went wrong</h1>
        <p className="mt-2 text-muted-foreground">
          {error?.message ?? "An unexpected error occurred."}
        </p>
      </div>
      <Button variant="outline" onClick={onReset}>
        Try Again
      </Button>
    </main>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Error Boundary (class component — only way to catch render errors)
// ─────────────────────────────────────────────────────────────────────────────

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class AppErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <ErrorFallback
          error={this.state.error}
          onReset={this.handleReset}
        />
      );
    }
    return this.props.children;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Step progress indicator
// ─────────────────────────────────────────────────────────────────────────────

const STEP_LABELS = [
  "Training Metadata",
  "Upload Files",
  "Review Matches",
  "Generate",
] as const;

function StepIndicator({ currentStep }: { currentStep: WizardStep }) {
  return (
    <nav className="mb-8 flex items-center justify-center gap-2">
      {STEP_LABELS.map((label, i) => {
        const stepNum = (i + 1) as WizardStep;
        const isActive = stepNum === currentStep;
        const isCompleted = stepNum < currentStep;

        let circleClass =
          "border-muted-foreground/30 text-muted-foreground";
        if (isActive) {
          circleClass = "border-primary bg-primary text-primary-foreground";
        } else if (isCompleted) {
          circleClass = "border-primary bg-primary/20 text-primary";
        }

        return (
          <div key={label} className="flex items-center gap-2">
            <div
              className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-medium transition-colors ${circleClass}`}
            >
              {isCompleted ? "\u2713" : stepNum}
            </div>
            <span
              className={`hidden sm:inline text-sm ${
                isActive
                  ? "font-medium text-foreground"
                  : "text-muted-foreground"
              }`}
            >
              {label}
            </span>
            {i < STEP_LABELS.length - 1 && (
              <div
                className={`hidden sm:block h-px w-8 transition-colors ${
                  isCompleted ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              />
            )}
          </div>
        );
      })}
    </nav>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main App (wizard state machine)
// ─────────────────────────────────────────────────────────────────────────────

function WizardApp() {
  // ── Core state ──────────────────────────────────────────────────────────

  const [step, setStep] = useState<WizardStep>(1);
  const [wizardState, setWizardState] = useState<WizardState>({
    metadata: null,
    uploadData: null,
    matchData: null,
    trainingMetadata: null,
  });
  const [sidecarReady, setSidecarReady] = useState(false);
  const [transitionPhase, setTransitionPhase] =
    useState<TransitionPhase>("idle");
  const [matchError, setMatchError] = useState<string | null>(null);

  // ── Tauri sidecar event listeners ───────────────────────────────────────

  useEffect(() => {
    const unlisteners: Array<() => void> = [];

    listen<unknown>("sidecar-ready", () => {
      setSidecarReady(true);
    }).then((unlisten) => {
      unlisteners.push(unlisten);
    });

    listen<string>("sidecar-stderr", (event) => {
      console.log("[sidecar-stderr]", event.payload);
    }).then((unlisten) => {
      unlisteners.push(unlisten);
    });

    // Fallback: if no event within 8 s, proceed anyway (dev without sidecar)
    const fallback = setTimeout(() => {
      setSidecarReady(true);
      console.warn(
        "[App] sidecar-ready not received after 8 s — proceeding without sidecar",
      );
    }, 8000);

    return () => {
      clearTimeout(fallback);
      unlisteners.forEach((fn) => fn());
    };
  }, []);

  // ── Navigation callbacks ────────────────────────────────────────────────

  /** Step 1 → Step 2: save metadata, advance. */
  const goToStep2 = useCallback((data: MetadataFormData) => {
    setWizardState((prev) => ({ ...prev, metadata: data }));
    setStep(2);
  }, []);

  /** Step 2 → Step 3: save upload data, run initial match API call, advance. */
  const goToStep3 = useCallback(async (data: UploadData) => {
    setWizardState((prev) => ({ ...prev, uploadData: data }));
    setTransitionPhase("matching");
    setMatchError(null);

    try {
      const participants = data.zoomParticipants.map(toParticipantSummary);
      const requests = data.ceRequests.map(toCERequestSummary);

      const response = await fetch(`${API_BASE}/api/match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zoom_participants: participants,
          ce_requests: requests,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Server returned ${response.status}: ${text}`);
      }

      const body: { matches: MatchEntryWire[] } = await response.json();

      const matchData: MatchData = {
        matches: body.matches,
        overrides: {},
        zoomParticipants: participants,
        ceRequests: requests,
      };

      setWizardState((prev) => ({ ...prev, matchData }));
      setStep(3);
      setTransitionPhase("idle");
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "An unknown error occurred during matching.";
      toast.error("Matching failed", { description: message });
      setMatchError(message);
      setTransitionPhase("idle");
    }
  }, []);

  /** Step 3 → Step 4: save (potentially corrected) match data, derive training, advance. */
  const goToStep4 = useCallback((data: MatchData) => {
    setWizardState((prev) => {
      const { metadata, uploadData } = prev;
      if (!metadata || !uploadData) return prev;
      const trainingMetadata = deriveTrainingMetadata(metadata, uploadData);
      return { ...prev, matchData: data, trainingMetadata };
    });
    setStep(4);
  }, []);

  /** Step N → Step N-1: preserve all state; each step restores from initialData. */
  const goBack = useCallback(() => {
    setStep((prev) => {
      if (prev <= 1) return 1;
      return (prev - 1) as WizardStep;
    });
  }, []);

  /** Step 4 → Step 1: clear all accumulated state, start fresh. */
  const resetWizard = useCallback(() => {
    setWizardState({
      metadata: null,
      uploadData: null,
      matchData: null,
      trainingMetadata: null,
    });
    setStep(1);
    setMatchError(null);
  }, []);

  // ── Context value (memoised to avoid re-renders) ────────────────────────

  const contextValue = useMemo<WizardContextValue>(
    () => ({ step, state: wizardState }),
    [step, wizardState],
  );

  // ── Loading screen (before sidecar signals ready) ───────────────────────

  if (!sidecarReady) {
    return <LoadingScreen />;
  }

  // ── Matching transition overlay ─────────────────────────────────────────

  if (transitionPhase === "matching") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4">
        {matchError ? (
          <>
            <AlertCircle className="h-12 w-12 text-destructive" />
            <h1 className="text-xl font-bold">Matching Failed</h1>
            <p className="max-w-md text-center text-muted-foreground">
              {matchError}
            </p>
            <div className="flex gap-3 pt-2">
              <Button
                variant="outline"
                onClick={() => {
                  setTransitionPhase("idle");
                }}
              >
                Go Back
              </Button>
              <Button
                onClick={() => {
                  goToStep3(wizardState.uploadData!);
                }}
              >
                Retry
              </Button>
            </div>
          </>
        ) : (
          <>
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <h1 className="text-xl font-bold">Matching Participants</h1>
            <p className="text-muted-foreground">
              Automatically matching Qualtrics names to Zoom attendees…
            </p>
          </>
        )}
      </main>
    );
  }

  // ── Wizard rendering ────────────────────────────────────────────────────

  return (
    <WizardContext.Provider value={contextValue}>
      <main className="min-h-screen bg-background px-4 py-8">
        <div className="mx-auto max-w-5xl">
          <StepIndicator currentStep={step} />

          {step === 1 && (
            <StepMetadata
              onNext={goToStep2}
              initialData={wizardState.metadata ?? undefined}
            />
          )}

          {step === 2 && (
            <StepUpload
              onNext={goToStep3}
              onBack={goBack}
              initialData={wizardState.uploadData ?? undefined}
            />
          )}

          {step === 3 && wizardState.matchData && (
            <StepMatchReview
              onNext={goToStep4}
              onBack={goBack}
              initialData={wizardState.matchData}
            />
          )}

          {step === 4 && wizardState.matchData && wizardState.trainingMetadata && (
            <StepGenerate
              onBack={goBack}
              onReset={resetWizard}
              matchData={wizardState.matchData}
              trainingMetadata={wizardState.trainingMetadata}
            />
          )}
        </div>
      </main>
    </WizardContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Default export — ErrorBoundary + Toast notifications
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <AppErrorBoundary>
      <WizardApp />
      <Toaster richColors position="bottom-right" />
    </AppErrorBoundary>
  );
}
