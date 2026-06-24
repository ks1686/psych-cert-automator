import { useState, useCallback, useMemo } from "react";
import { CheckCircle, AlertTriangle, XCircle, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ── Wire types (mirroring FastAPI schemas) ───────────────────────────────────

export interface AttendanceWire {
  is_eligible: boolean;
  late_join: number;
  early_leave: number;
  gaps: number;
  total_missed: number;
  total_attended: number;
  failure_reason: string | null;
}

export interface MatchEntryWire {
  kind: "success" | "ambiguous" | "not_found";
  qualtrics_name: string;
  zoom_name: string | null;
  confidence: number | null;
  candidates: string[] | null;
  attendance: AttendanceWire | null;
}

export interface ParticipantSummary {
  name: string;
  first_join: string;
  last_leave: string;
  total_attended_minutes: number;
  segments_count: number;
}

export interface CERequestSummary {
  name_on_certificate: string;
  email: string | null;
  ce_type: string;
  license_number: string | null;
}

export interface MatchData {
  matches: MatchEntryWire[];
  overrides: Record<string, string>;
  zoomParticipants: ParticipantSummary[];
  ceRequests: CERequestSummary[];
}

// ── Props ───────────────────────────────────────────────────────────────────

interface StepMatchReviewProps {
  onNext: (data: MatchData) => void;
  onBack: () => void;
  initialData: MatchData;
}

// ── Constants ───────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8000";

// ── Helpers ─────────────────────────────────────────────────────────────────

function confidencePercent(c: number | null): string {
  if (c === null) return "—";
  return `${Math.round(c * 100)}%`;
}

function formatAttendanceMinutes(attendance: AttendanceWire | null): string {
  if (!attendance) return "—";
  return `${attendance.total_attended}m / missed ${attendance.total_missed.toFixed(1)}m`;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function StepMatchReview({
  onNext,
  onBack,
  initialData,
}: StepMatchReviewProps) {
  const [matches, setMatches] = useState<MatchEntryWire[]>(initialData.matches);
  const [overrides, setOverrides] = useState<Record<string, string>>(
    { ...initialData.overrides },
  );
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Derive counts for the summary bar
  const summary = useMemo(() => {
    let matched = 0;
    let ambiguous = 0;
    let notFound = 0;
    let ineligible = 0;

    for (const m of matches) {
      switch (m.kind) {
        case "success": {
          matched++;
          if (m.attendance && !m.attendance.is_eligible) {
            ineligible++;
          }
          break;
        }
        case "ambiguous":
          ambiguous++;
          break;
        case "not_found":
          notFound++;
          break;
      }
    }

    return { matched, ambiguous, notFound, ineligible };
  }, [matches]);

  // All Zoom participant names (for not_found dropdown)
  const zoomNames = useMemo(
    () =>
      initialData.zoomParticipants
        .map((p) => p.name)
        .filter((n) => n.length > 0)
        .sort(),
    [initialData.zoomParticipants],
  );

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleSelectionChange = useCallback(
    (qualtricsName: string, zoomName: string) => {
      setOverrides((prev) => {
        if (zoomName === "__skip__") {
          // Remove override for this person
          const next = { ...prev };
          delete next[qualtricsName];
          return next;
        }
        return { ...prev, [qualtricsName]: zoomName };
      });
    },
    [],
  );

  const handleApplyCorrections = useCallback(async () => {
    setIsApplying(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zoom_participants: initialData.zoomParticipants,
          ce_requests: initialData.ceRequests,
          overrides:
            Object.keys(overrides).length > 0 ? overrides : undefined,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Server returned ${response.status}: ${text}`);
      }

      const data: { matches: MatchEntryWire[] } = await response.json();
      setMatches(data.matches);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to apply corrections",
      );
    } finally {
      setIsApplying(false);
    }
  }, [overrides, initialData.zoomParticipants, initialData.ceRequests]);

  const handleAutoMatch = useCallback(() => {
    onNext({
      matches,
      overrides,
      zoomParticipants: initialData.zoomParticipants,
      ceRequests: initialData.ceRequests,
    });
  }, [matches, overrides, initialData, onNext]);

  const handleNext = useCallback(() => {
    onNext({
      matches,
      overrides,
      zoomParticipants: initialData.zoomParticipants,
      ceRequests: initialData.ceRequests,
    });
  }, [matches, overrides, initialData, onNext]);

  // ── Render helpers ──────────────────────────────────────────────────────

  function renderStatusBadge(match: MatchEntryWire) {
    switch (match.kind) {
      case "success": {
        const isIneligible =
          match.attendance && !match.attendance.is_eligible;
        if (isIneligible) {
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Badge className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100 cursor-help">
                    <AlertTriangle className="mr-1 h-3 w-3" />
                    Matched (Ineligible)
                  </Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p className="max-w-xs">
                  {match.attendance?.failure_reason ?? "Does not meet attendance requirements"}
                </p>
              </TooltipContent>
            </Tooltip>
          );
        }
        return (
          <Badge className="border-transparent bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100">
            <CheckCircle className="mr-1 h-3 w-3" />
            Matched
          </Badge>
        );
      }
      case "ambiguous":
        return (
          <Badge className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100">
            <AlertTriangle className="mr-1 h-3 w-3" />
            Ambiguous
          </Badge>
        );
      case "not_found":
        return (
          <Badge className="border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100">
            <XCircle className="mr-1 h-3 w-3" />
            Not Found
          </Badge>
        );
    }
  }

  function renderActionCell(match: MatchEntryWire) {
    if (match.kind === "success") {
      return (
        <span className="text-sm text-muted-foreground">—</span>
      );
    }

    if (match.kind === "ambiguous" && match.candidates && match.candidates.length > 0) {
      const currentValue =
        overrides[match.qualtrics_name] ?? "";
      return (
        <Select
          value={currentValue}
          onValueChange={(v) =>
            handleSelectionChange(match.qualtrics_name, v)
          }
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Select match..." />
          </SelectTrigger>
          <SelectContent>
            {match.candidates.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    if (match.kind === "not_found") {
      const currentValue =
        overrides[match.qualtrics_name] ?? "";
      return (
        <Select
          value={currentValue}
          onValueChange={(v) =>
            handleSelectionChange(match.qualtrics_name, v)
          }
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Select match..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__skip__">Skip (leave unmatched)</SelectItem>
            {zoomNames.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    return null;
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const overrideCount = Object.keys(overrides).length;

  return (
    <TooltipProvider>
      <Card className="w-full max-w-5xl mx-auto">
        <CardHeader>
          <CardTitle className="text-xl">Review Name Matches</CardTitle>
          <p className="text-sm text-muted-foreground">
            Review the automatic name matching results. Use the dropdowns to
            correct ambiguous or unmatched names, then click{" "}
            <strong>Apply Corrections</strong> to re-run matching.
          </p>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* ── Summary bar ──────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 p-3 text-sm">
            <Badge variant="secondary" className="border-transparent bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100">
              {summary.matched} matched
            </Badge>
            <Badge variant="secondary" className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100">
              {summary.ambiguous} ambiguous
            </Badge>
            <Badge variant="secondary" className="border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100">
              {summary.notFound} not found
            </Badge>
            {summary.ineligible > 0 && (
              <Badge variant="secondary" className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100">
                {summary.ineligible} ineligible
              </Badge>
            )}
            {overrideCount > 0 && (
              <span className="ml-auto text-muted-foreground">
                {overrideCount} pending correction{overrideCount !== 1 ? "s" : ""}
              </span>
            )}
          </div>

          {/* ── Error banner ─────────────────────────────────────────── */}
          {error && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* ── Table ────────────────────────────────────────────────── */}
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Qualtrics Name</TableHead>
                  <TableHead>Zoom Name (Matched)</TableHead>
                  <TableHead className="w-[100px]">Confidence</TableHead>
                  <TableHead className="w-[140px]">Status</TableHead>
                  <TableHead className="w-[180px]">Attendance</TableHead>
                  <TableHead className="w-[220px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {matches.map((match) => {
                  const isIneligibleRow =
                    match.kind === "success" &&
                    match.attendance &&
                    !match.attendance.is_eligible;

                  return (
                    <TableRow
                      key={match.qualtrics_name}
                      className={
                        isIneligibleRow ? "bg-yellow-50 dark:bg-yellow-950/30" : ""
                      }
                    >
                      {/* Qualtrics Name */}
                      <TableCell className="font-medium">
                        {match.qualtrics_name}
                      </TableCell>

                      {/* Zoom Name */}
                      <TableCell>
                        {match.zoom_name ?? (
                          <span className="text-muted-foreground italic">
                            —
                          </span>
                        )}
                      </TableCell>

                      {/* Confidence */}
                      <TableCell>
                        {match.kind === "success" && match.confidence !== null ? (
                          <span className="tabular-nums">
                            {confidencePercent(match.confidence)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* Status */}
                      <TableCell>{renderStatusBadge(match)}</TableCell>

                      {/* Attendance */}
                      <TableCell>
                        {match.kind === "success" && match.attendance ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="cursor-help text-sm tabular-nums">
                                {match.attendance.is_eligible ? (
                                  <span className="text-green-700 dark:text-green-400">
                                    Eligible ({match.attendance.total_attended}m)
                                  </span>
                                ) : (
                                  <span className="text-yellow-700 dark:text-yellow-400">
                                    Ineligible{" "}
                                    {formatAttendanceMinutes(match.attendance)}
                                  </span>
                                )}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="left" className="max-w-xs">
                              <div className="space-y-1 text-xs">
                                <p>
                                  <strong>Late join:</strong>{" "}
                                  {match.attendance.late_join.toFixed(1)}m
                                </p>
                                <p>
                                  <strong>Early leave:</strong>{" "}
                                  {match.attendance.early_leave.toFixed(1)}m
                                </p>
                                <p>
                                  <strong>Gaps:</strong>{" "}
                                  {match.attendance.gaps.toFixed(1)}m
                                </p>
                                <p>
                                  <strong>Total missed:</strong>{" "}
                                  {match.attendance.total_missed.toFixed(1)}m
                                </p>
                                {match.attendance.failure_reason && (
                                  <p className="pt-1 text-destructive">
                                    {match.attendance.failure_reason}
                                  </p>
                                )}
                              </div>
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <span className="text-muted-foreground text-sm">
                            —
                          </span>
                        )}
                      </TableCell>

                      {/* Actions */}
                      <TableCell>{renderActionCell(match)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>

        <CardFooter className="flex items-center justify-between gap-2">
          <Button variant="outline" onClick={onBack}>
            Back
          </Button>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleApplyCorrections}
              disabled={isApplying || overrideCount === 0}
            >
              {isApplying ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Applying...
                </>
              ) : (
                "Apply Corrections"
              )}
            </Button>

            <Button variant="outline" onClick={handleAutoMatch}>
              Auto-match All
            </Button>

            <Button onClick={handleNext}>Next</Button>
          </div>
        </CardFooter>
      </Card>
    </TooltipProvider>
  );
}
