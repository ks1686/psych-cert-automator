import { useState, useMemo, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export interface MetadataFormData {
  title: string;
  date: string;
  instructor: string;
  ceCredits: number;
  ceTypes: {
    apa: boolean;
    nasp: boolean;
    bcba: boolean;
  };
  startTime: string;
  endTime: string;
}

interface SavedSession {
  id: number;
  title: string;
  date: string;
  instructor: string;
  ce_credits: number;
  ce_types: string;
  start_time: string;
  end_time: string;
}

interface StepMetadataProps {
  onNext: (data: MetadataFormData) => void;
  initialData?: MetadataFormData;
}

const EMPTY_FORM: MetadataFormData = {
  title: "",
  date: "",
  instructor: "",
  ceCredits: 0,
  ceTypes: { apa: false, nasp: false, bcba: false },
  startTime: "",
  endTime: "",
};

function validateFields(data: MetadataFormData): Record<string, string> {
  const errors: Record<string, string> = {};

  if (!data.title.trim()) {
    errors.title = "Training title is required.";
  }
  if (!data.date) {
    errors.date = "Date is required.";
  }
  if (!data.instructor.trim()) {
    errors.instructor = "Instructor name is required.";
  }
  if (!Number.isFinite(data.ceCredits) || data.ceCredits < 1) {
    errors.ceCredits = "CE credits must be at least 1.";
  }
  if (!data.ceTypes.apa && !data.ceTypes.nasp && !data.ceTypes.bcba) {
    errors.ceTypes = "At least one CE type must be selected.";
  }
  if (!data.startTime) {
    errors.startTime = "Start time is required.";
  }
  if (!data.endTime) {
    errors.endTime = "End time is required.";
  }
  if (data.startTime && data.endTime && data.startTime >= data.endTime) {
    errors.endTime = "End time must be after start time.";
  }

  return errors;
}

function ceTypesToString(ceTypes: MetadataFormData["ceTypes"]): string {
  const selected: string[] = [];
  if (ceTypes.apa) selected.push("APA");
  if (ceTypes.nasp) selected.push("NASP");
  if (ceTypes.bcba) selected.push("BCBA");
  return selected.join(",");
}

function parseCeTypes(typesStr: string): MetadataFormData["ceTypes"] {
  const parts = typesStr.split(",").map((s) => s.trim().toUpperCase());
  return {
    apa: parts.includes("APA"),
    nasp: parts.includes("NASP"),
    bcba: parts.includes("BCBA"),
  };
}

export default function StepMetadata({
  onNext,
  initialData,
}: StepMetadataProps) {
  const [formData, setFormData] = useState<MetadataFormData>(
    initialData ?? EMPTY_FORM,
  );
  const [sessions, setSessions] = useState<SavedSession[]>([]);
  const [showSessions, setShowSessions] = useState(false);
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [loadError, setLoadError] = useState<string | null>(null);

  const errors = useMemo(() => validateFields(formData), [formData]);
  const isValid = Object.keys(errors).length === 0;

  const updateField = useCallback(
    <K extends keyof MetadataFormData>(
      field: K,
      value: MetadataFormData[K],
    ) => {
      setFormData((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const updateCeType = useCallback(
    (type: keyof MetadataFormData["ceTypes"], checked: boolean | "indeterminate") => {
      setFormData((prev) => ({
        ...prev,
        ceTypes: { ...prev.ceTypes, [type]: checked === true },
      }));
    },
    [],
  );

  const handleSave = useCallback(async () => {
    setSaveStatus("saving");
    try {
      const response = await fetch("http://localhost:8008/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: formData.title,
          date: formData.date,
          instructor: formData.instructor,
          ce_credits: formData.ceCredits,
          ce_types: ceTypesToString(formData.ceTypes),
          start_time: formData.startTime,
          end_time: formData.endTime,
        }),
      });
      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch (err) {
      console.error("Failed to save session:", err);
      setSaveStatus("error");
      setTimeout(() => setSaveStatus("idle"), 3000);
    }
  }, [formData]);

  const handleLoad = useCallback(async () => {
    setLoadError(null);
    try {
      const response = await fetch("http://localhost:8008/api/sessions");
      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }
      const data: SavedSession[] = await response.json();
      setSessions(data);
      setShowSessions(true);
    } catch (err) {
      console.error("Failed to load sessions:", err);
      setLoadError("Failed to load sessions. Is the backend running?");
    }
  }, []);

  const handleSelectSession = useCallback((session: SavedSession) => {
    setFormData({
      title: session.title,
      date: session.date,
      instructor: session.instructor,
      ceCredits: session.ce_credits,
      ceTypes: parseCeTypes(session.ce_types),
      startTime: session.start_time,
      endTime: session.end_time,
    });
    setShowSessions(false);
  }, []);

  const handleNext = useCallback(() => {
    if (isValid) {
      onNext(formData);
    }
  }, [isValid, formData, onNext]);

  const getSaveButtonText = () => {
    switch (saveStatus) {
      case "saving":
        return "Saving...";
      case "saved":
        return "Saved!";
      case "error":
        return "Save Failed";
      default:
        return "Save Session";
    }
  };

  return (
    <Card className="mx-auto w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Training Metadata</CardTitle>
        <CardDescription>
          Enter the details for your CE training session. All fields are
          required.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Training Title */}
        <div className="space-y-2">
          <Label htmlFor="title">Training Title</Label>
          <Input
            id="title"
            type="text"
            placeholder="e.g. Ethics in School Psychology"
            value={formData.title}
            onChange={(e) => updateField("title", e.target.value)}
          />
          {errors.title && (
            <p className="text-destructive text-sm">{errors.title}</p>
          )}
        </div>

        {/* Date */}
        <div className="space-y-2">
          <Label htmlFor="date">Date</Label>
          <Input
            id="date"
            type="date"
            value={formData.date}
            onChange={(e) => updateField("date", e.target.value)}
          />
          {errors.date && (
            <p className="text-destructive text-sm">{errors.date}</p>
          )}
        </div>

        {/* Instructor Name */}
        <div className="space-y-2">
          <Label htmlFor="instructor">Instructor Name</Label>
          <Input
            id="instructor"
            type="text"
            placeholder="e.g. Dr. Jane Smith"
            value={formData.instructor}
            onChange={(e) => updateField("instructor", e.target.value)}
          />
          {errors.instructor && (
            <p className="text-destructive text-sm">{errors.instructor}</p>
          )}
        </div>

        {/* CE Credits */}
        <div className="space-y-2">
          <Label htmlFor="ceCredits">CE Credits</Label>
          <Input
            id="ceCredits"
            type="number"
            min={1}
            placeholder="3"
            value={formData.ceCredits || ""}
            onChange={(e) => {
              const val = e.target.value === "" ? 0 : Number(e.target.value);
              updateField("ceCredits", val);
            }}
          />
          {errors.ceCredits && (
            <p className="text-destructive text-sm">{errors.ceCredits}</p>
          )}
        </div>

        {/* CE Types */}
        <div className="space-y-2">
          <Label>CE Types</Label>
          <div className="flex flex-wrap gap-6 pt-1">
            <div className="flex items-center gap-2">
              <Checkbox
                id="apa"
                checked={formData.ceTypes.apa}
                onCheckedChange={(checked) => updateCeType("apa", checked)}
              />
              <Label htmlFor="apa" className="cursor-pointer font-normal">
                APA
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="nasp"
                checked={formData.ceTypes.nasp}
                onCheckedChange={(checked) => updateCeType("nasp", checked)}
              />
              <Label htmlFor="nasp" className="cursor-pointer font-normal">
                NASP
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="bcba"
                checked={formData.ceTypes.bcba}
                onCheckedChange={(checked) => updateCeType("bcba", checked)}
              />
              <Label htmlFor="bcba" className="cursor-pointer font-normal">
                BCBA
              </Label>
            </div>
          </div>
          {errors.ceTypes && (
            <p className="text-destructive text-sm">{errors.ceTypes}</p>
          )}
        </div>

        {/* Start Time & End Time */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="startTime">Start Time</Label>
            <Input
              id="startTime"
              type="time"
              value={formData.startTime}
              onChange={(e) => updateField("startTime", e.target.value)}
            />
            {errors.startTime && (
              <p className="text-destructive text-sm">{errors.startTime}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="endTime">End Time</Label>
            <Input
              id="endTime"
              type="time"
              value={formData.endTime}
              onChange={(e) => updateField("endTime", e.target.value)}
            />
            {errors.endTime && (
              <p className="text-destructive text-sm">{errors.endTime}</p>
            )}
          </div>
        </div>

        {/* Error summary for end time comparison (global error not tied to endTime key) */}
        {/* endTime already covers the comparison error, so no extra element needed */}

        {/* Saved Sessions List */}
        {showSessions && sessions.length > 0 && (
          <div className="rounded-md border p-4">
            <h3 className="mb-3 text-sm font-semibold">Saved Sessions</h3>
            <ul className="space-y-2">
              {sessions.map((session) => (
                <li key={session.id}>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto w-full justify-start px-3 py-2 text-left"
                    onClick={() => handleSelectSession(session)}
                  >
                    <span className="font-medium">{session.title}</span>
                    <span className="mx-2 text-muted-foreground">&mdash;</span>
                    <span className="text-muted-foreground">
                      {session.date} &middot; {session.instructor}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {showSessions && sessions.length === 0 && !loadError && (
          <p className="text-sm text-muted-foreground">
            No saved sessions found.
          </p>
        )}
        {loadError && (
          <p className="text-sm text-destructive">{loadError}</p>
        )}
      </CardContent>

      <CardFooter className="flex justify-between gap-3">
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleSave}
            disabled={saveStatus === "saving"}
          >
            {getSaveButtonText()}
          </Button>
          <Button variant="outline" onClick={handleLoad}>
            Load Session
          </Button>
        </div>
        <Button onClick={handleNext} disabled={!isValid}>
          Next
        </Button>
      </CardFooter>
    </Card>
  );
}
