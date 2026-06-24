import { useState, useCallback, useMemo } from "react";
import {
  Loader2,
  Download,
  Eye,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RotateCcw,
  FileDown,
  ArrowUpDown,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PdfPreview } from "@/components/PdfPreview";
import type { MatchData } from "@/components/StepMatchReview";

// ── Wire types ──────────────────────────────────────────────────────────────

export interface TrainingMetadata {
  title: string;
  date: string;
  instructor_name: string;
  ce_credits: number;
  ce_types_offered: string[];
  session_start: string;
  session_end: string;
}

export interface CertificateResult {
  name: string;
  ce_type: string;
  filename: string;
}

export interface IneligibleResult {
  name: string;
  status: IneligibleStatus;
  reason: string;
}

export type IneligibleStatus = "Not Found" | "Attendance" | "Ambiguous";

// ── SSE event types ─────────────────────────────────────────────────────────

interface SSEProgressEvent {
  type: "progress";
  current: number;
  total: number;
  success_count: number;
  failure_count: number;
}

interface SSECompleteEvent {
  type: "complete";
  certificates: CertificateResult[];
  ineligible: IneligibleResult[];
}

interface SSEErrorEvent {
  type: "error";
  message: string;
}

type SSEEvent = SSEProgressEvent | SSECompleteEvent | SSEErrorEvent;

// ── Component state enum ────────────────────────────────────────────────────

type GenerationPhase =
  | "initial"
  | "previewing"
  | "generating"
  | "complete";

// ── Eligible match (resolved from MatchData) ────────────────────────────────

interface EligibleEntry {
  qualtrics_name: string;
  zoom_name: string;
  ce_type: string;
  name_on_certificate: string;
  email: string | null;
  license_number: string | null;
}

// ── Props ───────────────────────────────────────────────────────────────────

interface StepGenerateProps {
  onBack: () => void;
  onReset: () => void;
  matchData: MatchData;
  trainingMetadata: TrainingMetadata;
}

// ── Constants ───────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8008";

// ── Helpers ─────────────────────────────────────────────────────────────────

function resolveEligibleEntries(matchData: MatchData): EligibleEntry[] {
  const entries: EligibleEntry[] = [];

  for (const match of matchData.matches) {
    if (match.kind !== "success") continue;
    if (!match.attendance?.is_eligible) continue;

    // Find corresponding CE requests for this Qualtrics name.
    // A single person may have multiple CE requests (one per CE type).
    const matchingRequests = matchData.ceRequests.filter(
      (req) => req.name_on_certificate === match.qualtrics_name,
    );

    for (const req of matchingRequests) {
      entries.push({
        qualtrics_name: match.qualtrics_name,
        zoom_name: match.zoom_name ?? match.qualtrics_name,
        ce_type: req.ce_type,
        name_on_certificate: req.name_on_certificate,
        email: req.email,
        license_number: req.license_number,
      });
    }
  }

  return entries;
}

function deriveIneligibleEntries(
  matchData: MatchData,
): IneligibleResult[] {
  const results: IneligibleResult[] = [];

  for (const match of matchData.matches) {
    if (match.kind === "not_found") {
      results.push({
        name: match.qualtrics_name,
        status: "Not Found",
        reason: "No matching Zoom participant found for this name.",
      });
    } else if (match.kind === "ambiguous") {
      results.push({
        name: match.qualtrics_name,
        status: "Ambiguous",
        reason: `Multiple possible Zoom matches: ${(match.candidates ?? []).join(", ")}`,
      });
    } else if (
      match.kind === "success" &&
      match.attendance &&
      !match.attendance.is_eligible
    ) {
      results.push({
        name: match.qualtrics_name,
        status: "Attendance",
        reason:
          match.attendance.failure_reason ??
          "Does not meet minimum attendance requirements.",
      });
    }
  }

  return results;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function StepGenerate({
  onBack,
  onReset,
  matchData,
  trainingMetadata,
}: StepGenerateProps) {
  // ── Derived data ────────────────────────────────────────────────────────

  const eligibleEntries = useMemo(
    () => resolveEligibleEntries(matchData),
    [matchData],
  );

  const derivedIneligible = useMemo(
    () => deriveIneligibleEntries(matchData),
    [matchData],
  );

  // ── Phase state ──────────────────────────────────────────────────────────

  const [phase, setPhase] = useState<GenerationPhase>("initial");

  // ── Preview state ────────────────────────────────────────────────────────

  const [previewPdfBytes, setPreviewPdfBytes] = useState<Uint8Array | null>(
    null,
  );
  const [previewError, setPreviewError] = useState<string | null>(null);

  // ── Generation state ─────────────────────────────────────────────────────

  const [progressPercent, setProgressPercent] = useState(0);
  const [progressLabel, setProgressLabel] = useState("");
  const [successCount, setSuccessCount] = useState(0);
  const [failureCount, setFailureCount] = useState(0);
  const [genError, setGenError] = useState<string | null>(null);

  // ── Results state ────────────────────────────────────────────────────────

  const [certificates, setCertificates] = useState<CertificateResult[]>([]);
  const [ineligible, setIneligible] = useState<IneligibleResult[]>([]);

  // ── Ineligibility table filter & sort ────────────────────────────────────

  const [eligFilter, setEligFilter] = useState<IneligibleStatus | "All">("All");
  const [eligSortKey, setEligSortKey] = useState<
    "name" | "status" | "reason"
  >("name");
  const [eligSortDir, setEligSortDir] = useState<"asc" | "desc">("asc");

  // ── Preview handler ──────────────────────────────────────────────────────

  const handlePreview = useCallback(async () => {
    if (eligibleEntries.length === 0) return;

    setPhase("previewing");
    setPreviewError(null);
    setPreviewPdfBytes(null);

    try {
      const first = eligibleEntries[0];

      const response = await fetch(`${API_BASE}/api/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          training: trainingMetadata,
          entry: {
            qualtrics_name: first.qualtrics_name,
            zoom_name: first.zoom_name,
            ce_type: first.ce_type,
            name_on_certificate: first.name_on_certificate,
            email: first.email,
            license_number: first.license_number,
          },
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Preview failed (${response.status}): ${text}`);
      }

      const buffer = await response.arrayBuffer();
      setPreviewPdfBytes(new Uint8Array(buffer));
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : "Failed to generate preview",
      );
    } finally {
      setPhase("initial");
    }
  }, [eligibleEntries, trainingMetadata]);

  // ── SSE generation handler ───────────────────────────────────────────────

  const handleGenerate = useCallback(async () => {
    if (eligibleEntries.length === 0) return;

    setPhase("generating");
    setGenError(null);
    setProgressPercent(0);
    setProgressLabel("Starting…");
    setSuccessCount(0);
    setFailureCount(0);
    setCertificates([]);
    setIneligible([]);

    try {
      const response = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          training: trainingMetadata,
          certificates: eligibleEntries.map((e) => ({
            qualtrics_name: e.qualtrics_name,
            zoom_name: e.zoom_name,
            ce_type: e.ce_type,
            name_on_certificate: e.name_on_certificate,
            email: e.email,
            license_number: e.license_number,
          })),
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Generation failed (${response.status}): ${text}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body stream available");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split on double-newline (SSE event delimiter)
        const parts = buffer.split("\n\n");
        // Last part may be incomplete — keep it for next chunk
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const trimmed = part.trim();
          if (trimmed.length === 0) continue;

          // Extract the "data:" line
          const lines = trimmed.split("\n");
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const jsonStr = line.slice(6).trim();
              if (jsonStr.length === 0) continue;

              try {
                const event: SSEEvent = JSON.parse(jsonStr);
                handleSSEEvent(event);
              } catch {
                // Skip unparseable events
              }
            }
          }
        }
      }

      // Process any remaining data in buffer after stream ends
      if (buffer.trim().length > 0) {
        const lines = buffer.trim().split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const jsonStr = line.slice(6).trim();
            if (jsonStr.length === 0) continue;
            try {
              const event: SSEEvent = JSON.parse(jsonStr);
              handleSSEEvent(event);
            } catch {
              // Skip unparseable events
            }
          }
        }
      }
    } catch (err) {
      setGenError(
        err instanceof Error ? err.message : "Generation failed",
      );
      setPhase("initial");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eligibleEntries, trainingMetadata]);

  // SSE event handler (defined inside component so it can close over setters)
  function handleSSEEvent(event: SSEEvent) {
    switch (event.type) {
      case "progress": {
        setProgressLabel(
          `Generated ${event.current} of ${event.total} certificates…`,
        );
        setProgressPercent(
          event.total > 0 ? Math.round((event.current / event.total) * 100) : 0,
        );
        setSuccessCount(event.success_count);
        setFailureCount(event.failure_count);
        break;
      }
      case "complete": {
        setCertificates(event.certificates);
        setIneligible(
          event.ineligible.length > 0
            ? event.ineligible
            : derivedIneligible,
        );
        setPhase("complete");
        setProgressPercent(100);
        setProgressLabel("Generation complete");
        break;
      }
      case "error": {
        setGenError(event.message);
        setPhase("initial");
        break;
      }
    }
  }

  // ── ZIP download handler ──────────────────────────────────────────────────

  const handleDownloadZip = useCallback(async () => {
    try {
      const filenames = certificates.map((c) => c.filename);

      const response = await fetch(`${API_BASE}/api/download-zip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ files: filenames }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Download failed (${response.status}): ${text}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "certificates.zip";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setGenError(
        err instanceof Error ? err.message : "ZIP download failed",
      );
    }
  }, [certificates]);

  // ── Ineligibility table helpers ──────────────────────────────────────────

  const filteredIneligible = useMemo(() => {
    let list = [...ineligible];
    if (eligFilter !== "All") {
      list = list.filter((entry) => entry.status === eligFilter);
    }
    list.sort((a, b) => {
      let cmp = 0;
      if (eligSortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (eligSortKey === "status") cmp = a.status.localeCompare(b.status);
      else cmp = a.reason.localeCompare(b.reason);
      return eligSortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [ineligible, eligFilter, eligSortKey, eligSortDir]);

  const toggleSort = useCallback(
    (key: "name" | "status" | "reason") => {
      if (eligSortKey === key) {
        setEligSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setEligSortKey(key);
        setEligSortDir("asc");
      }
    },
    [eligSortKey],
  );

  const eligCounts = useMemo(() => {
    const counts: Record<IneligibleStatus | "All", number> = {
      All: ineligible.length,
      "Not Found": 0,
      Attendance: 0,
      Ambiguous: 0,
    };
    for (const e of ineligible) {
      counts[e.status] += 1;
    }
    return counts;
  }, [ineligible]);

  function statusBadge(status: IneligibleStatus) {
    switch (status) {
      case "Not Found":
        return (
          <Badge className="border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100">
            <XCircle className="mr-1 h-3 w-3" />
            Not Found
          </Badge>
        );
      case "Attendance":
        return (
          <Badge className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100">
            <AlertTriangle className="mr-1 h-3 w-3" />
            Attendance
          </Badge>
        );
      case "Ambiguous":
        return (
          <Badge className="border-transparent bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-100">
            <AlertTriangle className="mr-1 h-3 w-3" />
            Ambiguous
          </Badge>
        );
    }
  }

  // ── Derived: can preview? ─────────────────────────────────────────────────

  const canPreview = eligibleEntries.length > 0 && phase !== "generating";

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Card className="w-full max-w-5xl mx-auto">
      <CardHeader>
        <CardTitle className="text-xl">Generate Certificates</CardTitle>
        <p className="text-sm text-muted-foreground">
          {eligibleEntries.length > 0
            ? `${eligibleEntries.length} eligible certificate${eligibleEntries.length !== 1 ? "s" : ""} ready to generate.`
            : "No eligible certificates found. All participants are ineligible."}
        </p>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* ── Error banner ──────────────────────────────────────────────── */}
        {(previewError ?? genError) && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <p className="font-medium">Error</p>
            <p className="mt-1">{previewError ?? genError}</p>
          </div>
        )}

        {/* ── Preview sub-section ───────────────────────────────────────── */}
        {canPreview && (
          <div className="space-y-4 rounded-md border p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">
                  Preview Certificate
                </h3>
                <p className="text-xs text-muted-foreground">
                  Preview using the first eligible participant.
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handlePreview}
                disabled={phase === "previewing"}
              >
                {phase === "previewing" ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating Preview…
                  </>
                ) : (
                  <>
                    <Eye className="mr-2 h-4 w-4" />
                    Preview Certificate
                  </>
                )}
              </Button>
            </div>

            {previewPdfBytes && (
              <div className="rounded-md border bg-muted/20 p-2">
                <PdfPreview pdfBytes={previewPdfBytes} />
              </div>
            )}
          </div>
        )}

        {/* ── Generate sub-section ──────────────────────────────────────── */}
        {phase !== "complete" && (
          <div className="space-y-4 rounded-md border p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">
                  Batch Generation
                </h3>
                <p className="text-xs text-muted-foreground">
                  Generate all certificates at once with real-time progress.
                </p>
              </div>
              <Button
                onClick={handleGenerate}
                disabled={
                  phase === "generating" || eligibleEntries.length === 0
                }
              >
                {phase === "generating" ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    <FileDown className="mr-2 h-4 w-4" />
                    Generate All Certificates
                  </>
                )}
              </Button>
            </div>

            {/* Progress bar */}
            {phase === "generating" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    {progressLabel}
                  </span>
                  <span className="tabular-nums font-medium">
                    {progressPercent}%
                  </span>
                </div>
                <Progress value={progressPercent} />
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <CheckCircle className="h-3 w-3 text-green-600" />
                    {successCount} succeeded
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <XCircle className="h-3 w-3 text-red-600" />
                    {failureCount} failed
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Results sub-section (after generation) ────────────────────── */}
        {phase === "complete" && (
          <div className="space-y-6">
            {/* Certificate table */}
            {certificates.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">
                  Generated Certificates ({certificates.length})
                </h3>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>CE Type</TableHead>
                        <TableHead>Filename</TableHead>
                        <TableHead className="w-[80px]">View</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {certificates.map((cert) => (
                        <TableRow
                          key={`${cert.filename}-${cert.ce_type}-${cert.name}`}
                        >
                          <TableCell className="font-medium">
                            {cert.name}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="secondary"
                              className="text-xs"
                            >
                              {cert.ce_type}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">
                            {cert.filename}
                          </TableCell>
                          <TableCell>
                            <Button variant="ghost" size="sm" asChild>
                              <a
                                href={`${API_BASE}/api/pdf/${encodeURIComponent(cert.filename)}`}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                <Eye className="mr-1 h-3 w-3" />
                                View
                              </a>
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* Ineligibility report */}
            {filteredIneligible.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">
                  Ineligibility Report ({ineligible.length} total)
                </h3>

                {/* Filter buttons */}
                <div className="mb-3 flex flex-wrap items-center gap-1">
                  {(["All", "Not Found", "Attendance", "Ambiguous"] as const).map(
                    (filter) => (
                      <Button
                        key={filter}
                        variant={
                          eligFilter === filter ? "default" : "outline"
                        }
                        size="sm"
                        onClick={() => setEligFilter(filter)}
                        className="h-7 text-xs"
                      >
                        {filter}{" "}
                        <span className="ml-1 tabular-nums">
                          ({eligCounts[filter]})
                        </span>
                      </Button>
                    ),
                  )}
                </div>

                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead
                          className="cursor-pointer select-none"
                          onClick={() => toggleSort("name")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Name
                            <ArrowUpDown className="h-3 w-3" />
                          </span>
                        </TableHead>
                        <TableHead
                          className="cursor-pointer select-none w-[120px]"
                          onClick={() => toggleSort("status")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Status
                            <ArrowUpDown className="h-3 w-3" />
                          </span>
                        </TableHead>
                        <TableHead
                          className="cursor-pointer select-none"
                          onClick={() => toggleSort("reason")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Reason
                            <ArrowUpDown className="h-3 w-3" />
                          </span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredIneligible.map((entry) => (
                        <TableRow key={`${entry.name}-${entry.status}`}>
                          <TableCell className="font-medium">
                            {entry.name}
                          </TableCell>
                          <TableCell>
                            {statusBadge(entry.status)}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {entry.reason}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-2">
              <Button
                variant="outline"
                onClick={onReset}
              >
                <RotateCcw className="mr-2 h-4 w-4" />
                Start Over
              </Button>

              {certificates.length > 0 && (
                <Button onClick={handleDownloadZip}>
                  <Download className="mr-2 h-4 w-4" />
                  Download All as ZIP
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>

      <CardFooter className="flex items-center justify-between">
        <Button
          variant="outline"
          onClick={onBack}
          disabled={phase === "generating"}
        >
          Back
        </Button>
      </CardFooter>
    </Card>
  );
}
