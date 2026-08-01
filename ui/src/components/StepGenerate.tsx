import { useState, useCallback, useMemo } from "react";
import {
  Loader2,
  Download,
  Eye,
  CheckCircle,
  XCircle,
  RotateCcw,
  FileDown,
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
import {
  IneligibilityReport,
  type IneligibleResult,
} from "@/components/generate/IneligibilityReport";
import { API_BASE, pdfViewUrl } from "@/api/client";
import type { MatchData } from "@/components/StepMatchReview";
import type { UploadData } from "@/components/StepUpload";

export type { IneligibleResult, IneligibleStatus } from "@/components/generate/IneligibilityReport";

// ── Wire types ──────────────────────────────────────────────────────────────

export interface TrainingMetadata {
  title: string;
  date: string;
  end_date: string | null;
  instructor_name: string;
  ce_credits: number;
  ce_types_offered: string[];
  session_start: string;
  session_end: string;
  is_virtual: boolean;
  location: string | null;
}

export interface CertificateResult {
  name: string;
  ce_type: string;
  filename: string;
  path: string;
}

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
  uploadData: UploadData;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function resolveEligibleEntries(matchData: MatchData): EligibleEntry[] {
  const entries: EligibleEntry[] = [];
  const excluded = new Set(matchData.excludedNames);

  for (const match of matchData.matches) {
    if (match.kind !== "success") continue;
    if (!match.attendance?.is_eligible) continue;
    if (excluded.has(match.qualtrics_name)) continue;

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
  const excluded = new Set(matchData.excludedNames);

  for (const match of matchData.matches) {
    if (excluded.has(match.qualtrics_name)) {
      results.push({
        name: match.qualtrics_name,
        status: "Excluded",
        reason: "Excluded from certificate generation",
      });
      continue;
    }
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
  uploadData,
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
  const [conversionWarning, setConversionWarning] = useState(false);
  const [previewIsPdf, setPreviewIsPdf] = useState(true);

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
          full_name: first.name_on_certificate,
          ce_type: first.ce_type,
          ce_credits: trainingMetadata.ce_credits,
          training_title: trainingMetadata.title,
          training_date: trainingMetadata.date,
          instructor_name: trainingMetadata.instructor_name,
          license_number: first.license_number,
          is_virtual: trainingMetadata.is_virtual,
          location: trainingMetadata.location,
          end_date: trainingMetadata.end_date,
          start_time: trainingMetadata.session_start || null,
          end_time: trainingMetadata.session_end || null,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Preview failed (${response.status}): ${text}`);
      }

      const contentType = response.headers.get("content-type") ?? "";
      const buffer = await response.arrayBuffer();
      setPreviewIsPdf(contentType.includes("pdf"));
      setPreviewPdfBytes(new Uint8Array(buffer));
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : "Failed to generate preview",
      );
    } finally {
      setPhase("initial");
    }
  }, [eligibleEntries, trainingMetadata]);

  // ── Generation handler ───────────────────────────────────────────────────

  const handleGenerate = useCallback(async () => {
    if (eligibleEntries.length === 0) return;

    setPhase("generating");
    setGenError(null);
    setProgressPercent(10);
    setProgressLabel("Generating certificates…");
    setSuccessCount(0);
    setFailureCount(0);
    setCertificates([]);
    setIneligible([]);
    setConversionWarning(false);

    try {
      const response = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zoom_path: uploadData.zoomPath,
          qualtrics_path: uploadData.qualtricsPath,
          title: trainingMetadata.title,
          training_date: trainingMetadata.date,
          instructor: trainingMetadata.instructor_name,
          ce_credits: trainingMetadata.ce_credits,
          ce_types: trainingMetadata.ce_types_offered,
          start_time: trainingMetadata.session_start,
          end_time: trainingMetadata.session_end,
          overrides:
            Object.keys(matchData.overrides).length > 0
              ? matchData.overrides
              : undefined,
          excluded_names:
            matchData.excludedNames.length > 0
              ? matchData.excludedNames
              : undefined,
          is_virtual: trainingMetadata.is_virtual,
          location: trainingMetadata.location,
          end_date: trainingMetadata.end_date,
          output_dir: "./output",
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Generation failed (${response.status}): ${text}`);
      }

      const payload: {
        certificates: CertificateResult[];
        ineligible: IneligibleResult[];
        conversion_warning?: boolean;
      } = await response.json();

      setCertificates(payload.certificates);
      setIneligible(
        payload.ineligible.length > 0
          ? payload.ineligible
          : derivedIneligible,
      );
      setConversionWarning(payload.conversion_warning === true);
      setSuccessCount(payload.certificates.length);
      setFailureCount(payload.ineligible.length);
      setProgressPercent(100);
      setProgressLabel("Generation complete");
      setPhase("complete");
    } catch (err) {
      setGenError(
        err instanceof Error ? err.message : "Generation failed",
      );
      setPhase("initial");
    }
  }, [
    eligibleEntries.length,
    matchData.overrides,
    matchData.excludedNames,
    trainingMetadata,
    uploadData,
    derivedIneligible,
  ]);

  // ── ZIP download handler ──────────────────────────────────────────────────

  const handleDownloadZip = useCallback(async () => {
    try {
      const pdfPaths = certificates.map((c) => c.path);

      const response = await fetch(`${API_BASE}/api/download-zip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pdf_paths: pdfPaths }),
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

            {previewPdfBytes && previewIsPdf && (
              <div className="rounded-md border bg-muted/20 p-2">
                <PdfPreview pdfBytes={previewPdfBytes} />
              </div>
            )}
            {previewPdfBytes && !previewIsPdf && (
              <p className="text-sm text-muted-foreground">
                Preview returned a Word document (PDF converter not available on
                this machine). Generation will still write filled certificates.
              </p>
            )}
          </div>
        )}

        {/* ── Generate sub-section ──────────────────────────────────────── */}
        <div className="space-y-4 rounded-md border p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">
                  Batch Generation
                </h3>
                <p className="text-xs text-muted-foreground">
                  Generate all certificates at once. Safe to re-run after
                  deleting output files.
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
                ) : phase === "complete" ? (
                  <>
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Generate Again
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

        {/* ── Results sub-section (after generation) ────────────────────── */}
        {phase === "complete" && (
          <div className="space-y-6">
            {conversionWarning && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
                PDF conversion was unavailable on this machine. Filled Word
                (`.docx`) certificates were written instead. Install LibreOffice
                for PDF output on Windows, macOS, or Linux.
              </div>
            )}
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
                                href={pdfViewUrl(cert.path)}
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

            <IneligibilityReport entries={ineligible} />

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
