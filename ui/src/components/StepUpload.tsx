import { useState, useCallback } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { Loader2, Upload, FileSpreadsheet } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

interface ZoomParticipant {
  name_raw: string;
  first_join: string;
  last_leave: string;
  total_attended_minutes: number;
  segment_count: number;
}

interface CERequest {
  name_on_certificate: string;
  email: string | null;
  ce_type: string;
  license_number: string | null;
}

interface ParseResponse {
  session_start: string;
  session_end: string;
  participants: ZoomParticipant[];
  ce_requests: CERequest[];
  participant_count: number;
  request_count: number;
}

export interface UploadData {
  /** Absolute path to the Zoom attendance .xlsx file */
  zoomPath: string;
  /** Absolute path to the Qualtrics CE survey .xlsx file */
  qualtricsPath: string;
  /** Parsed Zoom participant summaries */
  zoomParticipants: ZoomParticipant[];
  /** Parsed Qualtrics CE credit requests */
  ceRequests: CERequest[];
  /** Total number of Zoom participants found */
  participantCount: number;
  /** Total number of CE credit requests found */
  requestCount: number;
  /** Earliest join time across all participants (ISO 8601) */
  sessionStart: string;
  /** Latest leave time across all participants (ISO 8601) */
  sessionEnd: string;
}

// ── Props ────────────────────────────────────────────────────────────────────

interface StepUploadProps {
  /** Called with populated UploadData once parsing succeeds */
  onNext: (data: UploadData) => void;
  /** Return to the previous wizard step */
  onBack: () => void;
  /** Pre-populated upload data when revisiting this step */
  initialData?: UploadData;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const BASE_URL = "http://localhost:8008";

function formatDatetime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function truncatePath(path: string, maxLen = 48): string {
  if (path.length <= maxLen) return path;
  return "…" + path.slice(path.length - maxLen + 1);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function StepUpload({
  onNext,
  onBack,
  initialData,
}: StepUploadProps) {
  const [zoomPath, setZoomPath] = useState<string>(
    initialData?.zoomPath ?? "",
  );
  const [qualtricsPath, setQualtricsPath] = useState<string>(
    initialData?.qualtricsPath ?? "",
  );

  // Parse result state
  const [parseResult, setParseResult] = useState<ParseResponse | null>(
    initialData
      ? {
          session_start: initialData.sessionStart,
          session_end: initialData.sessionEnd,
          participants: initialData.zoomParticipants,
          ce_requests: initialData.ceRequests,
          participant_count: initialData.participantCount,
          request_count: initialData.requestCount,
        }
      : null,
  );

  const [isParsing, setIsParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  // ── File picker handlers ──────────────────────────────────────────────────

  const handleSelectZoom = useCallback(async () => {
    try {
      const selected = await open({
        title: "Select Zoom Attendance Report",
        filters: [{ name: "Excel Files", extensions: ["xlsx"] }],
        multiple: false,
      });
      if (selected !== null && typeof selected === "string") {
        setZoomPath(selected);
        setParseResult(null);
        setParseError(null);
      }
    } catch {
      setParseError("Could not open file dialog. Is this running in Tauri?");
    }
  }, []);

  const handleSelectQualtrics = useCallback(async () => {
    try {
      const selected = await open({
        title: "Select Qualtrics CE Survey",
        filters: [{ name: "Excel Files", extensions: ["xlsx"] }],
        multiple: false,
      });
      if (selected !== null && typeof selected === "string") {
        setQualtricsPath(selected);
        setParseResult(null);
        setParseError(null);
      }
    } catch {
      setParseError("Could not open file dialog. Is this running in Tauri?");
    }
  }, []);

  // ── Parse handler ─────────────────────────────────────────────────────────

  const handleParse = useCallback(async () => {
    if (!zoomPath || !qualtricsPath) return;

    setIsParsing(true);
    setParseError(null);
    setParseResult(null);

    try {
      const response = await fetch(`${BASE_URL}/api/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          zoom_path: zoomPath,
          qualtrics_path: qualtricsPath,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(
          typeof body.detail === "string" ? body.detail : `Parse failed (HTTP ${response.status})`,
        );
      }

      const data: ParseResponse = await response.json();
      setParseResult(data);
    } catch (err) {
      setParseError(
        err instanceof Error ? err.message : "An unknown error occurred",
      );
    } finally {
      setIsParsing(false);
    }
  }, [zoomPath, qualtricsPath]);

  // ── Next handler ──────────────────────────────────────────────────────────

  const handleNext = useCallback(() => {
    if (!parseResult) return;
    onNext({
      zoomPath,
      qualtricsPath,
      zoomParticipants: parseResult.participants,
      ceRequests: parseResult.ce_requests,
      participantCount: parseResult.participant_count,
      requestCount: parseResult.request_count,
      sessionStart: parseResult.session_start,
      sessionEnd: parseResult.session_end,
    });
  }, [onNext, zoomPath, qualtricsPath, parseResult]);

  // ── Derived states ────────────────────────────────────────────────────────

  const canParse = zoomPath.length > 0 && qualtricsPath.length > 0 && !isParsing;
  const canProceed = parseResult !== null;

  const ceTypeColors: Record<string, string> = {
    APA: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    NASP: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
    BCBA: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
  };

  function ceVariant(ceType: string): string {
    return ceTypeColors[ceType] ?? "";
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Card className="w-full max-w-4xl mx-auto">
      <CardHeader>
        <CardTitle className="text-2xl">Step 2: Upload Files</CardTitle>
        <CardDescription>
          Select your Zoom attendance report and Qualtrics CE survey export.
          Both must be Excel (.xlsx) files.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* ── File picker: Zoom ─────────────────────────────────────────── */}
        <div className="space-y-2">
          <Label>Zoom Attendance Report</Label>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={handleSelectZoom}
              type="button"
            >
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              Select Zoom Report
            </Button>
            {zoomPath ? (
              <span
                className="text-sm text-muted-foreground truncate max-w-md"
                title={zoomPath}
              >
                {truncatePath(zoomPath)}
              </span>
            ) : (
              <span className="text-sm text-muted-foreground italic">
                No file selected
              </span>
            )}
          </div>
        </div>

        {/* ── File picker: Qualtrics ────────────────────────────────────── */}
        <div className="space-y-2">
          <Label>Qualtrics CE Survey</Label>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={handleSelectQualtrics}
              type="button"
            >
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              Select Qualtrics Survey
            </Button>
            {qualtricsPath ? (
              <span
                className="text-sm text-muted-foreground truncate max-w-md"
                title={qualtricsPath}
              >
                {truncatePath(qualtricsPath)}
              </span>
            ) : (
              <span className="text-sm text-muted-foreground italic">
                No file selected
              </span>
            )}
          </div>
        </div>

        {/* ── Parse button ──────────────────────────────────────────────── */}
        <div className="pt-2">
          <Button
            onClick={handleParse}
            disabled={!canParse}
            type="button"
            className="w-full sm:w-auto"
          >
            {isParsing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Parsing…
              </>
            ) : (
              <>
                <Upload className="mr-2 h-4 w-4" />
                Parse Files
              </>
            )}
          </Button>
        </div>

        {/* ── Error message ─────────────────────────────────────────────── */}
        {parseError && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <p className="font-medium">Parse Error</p>
            <p className="mt-1">{parseError}</p>
          </div>
        )}

        {/* ── Results ───────────────────────────────────────────────────── */}
        {parseResult && (
          <div className="space-y-6">
            {/* Summary */}
            <div className="rounded-md border bg-muted/30 px-4 py-3">
              <p className="text-sm font-medium">
                {parseResult.participant_count} participant
                {parseResult.participant_count !== 1 ? "s" : ""} found,{" "}
                {parseResult.request_count} CE request
                {parseResult.request_count !== 1 ? "s" : ""} found
              </p>
              {parseResult.session_start && parseResult.session_end && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Session: {formatDatetime(parseResult.session_start)} →{" "}
                  {formatDatetime(parseResult.session_end)}
                </p>
              )}
            </div>

            {/* Zoom Participants table */}
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Zoom Participants
              </h3>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>First Join</TableHead>
                      <TableHead>Last Leave</TableHead>
                      <TableHead className="text-right">
                        Total Attended (min)
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parseResult.participants.map((p, i) => (
                      <TableRow key={`${p.name_raw}-${i}`}>
                        <TableCell className="font-medium">
                          {p.name_raw}
                        </TableCell>
                        <TableCell>
                          {formatDatetime(p.first_join)}
                        </TableCell>
                        <TableCell>
                          {formatDatetime(p.last_leave)}
                        </TableCell>
                        <TableCell className="text-right">
                          {p.total_attended_minutes}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {/* Qualtrics CE Requests table */}
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Qualtrics CE Requests
              </h3>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>CE Type</TableHead>
                      <TableHead>License #</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parseResult.ce_requests.map((req, i) => (
                      <TableRow key={`${req.name_on_certificate}-${i}`}>
                        <TableCell className="font-medium">
                          {req.name_on_certificate}
                        </TableCell>
                        <TableCell>
                          {req.email ?? (
                            <span className="italic text-muted-foreground">
                              —
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            className={cn(
                              "font-mono text-xs",
                              ceVariant(req.ce_type),
                            )}
                          >
                            {req.ce_type}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {req.license_number ?? (
                            <span className="italic text-muted-foreground">
                              —
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          </div>
        )}
      </CardContent>

      <CardFooter className="flex items-center justify-between">
        <Button variant="outline" onClick={onBack} type="button">
          Back
        </Button>
        <Button onClick={handleNext} disabled={!canProceed} type="button">
          Next
        </Button>
      </CardFooter>
    </Card>
  );
}
