import { useEffect } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import App from "@/App";
import type { MetadataFormData } from "@/components/StepMetadata";
import type { UploadData } from "@/components/StepUpload";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => undefined),
}));

vi.mock("@/components/StartupScreen", () => ({
  default({ onReady }: { onReady: () => void }) {
    useEffect(() => {
      onReady();
    }, [onReady]);
    return null;
  },
}));

const metadata: MetadataFormData = {
  title: "Ethics",
  date: "2026-07-21",
  endDate: "",
  isMultiDay: false,
  instructor: "Dr. Jane Smith",
  ceCredits: 3,
  ceTypes: { apa: true, nasp: false, ny: false, nbcc: false },
  startTime: "09:00",
  endTime: "12:00",
  isVirtual: true,
  location: "",
};

vi.mock("@/components/StepMetadata", () => ({
  default({ onNext }: { onNext: (data: MetadataFormData) => void }) {
    return (
      <button type="button" onClick={() => onNext(metadata)}>
        Skip metadata
      </button>
    );
  },
}));

const uploadData: UploadData = {
  zoomPath: "/tmp/zoom.xlsx",
  qualtricsPath: "/tmp/qualtrics.xlsx",
  zoomParticipants: [
    {
      name_raw: "Alex Rivera",
      first_join: "2026-07-21T09:00:00",
      last_leave: "2026-07-21T12:00:00",
      total_attended_minutes: 180,
      segment_count: 1,
    },
  ],
  ceRequests: [
    {
      name_on_certificate: "Alex Rivera",
      email: "alex@example.com",
      ce_type: "APA",
      license_number: null,
    },
  ],
  participantCount: 1,
  requestCount: 1,
  sessionStart: "2026-07-21T09:00:00",
  sessionEnd: "2026-07-21T12:00:00",
  zoomHost: null,
};

vi.mock("@/components/StepUpload", () => ({
  default({ onNext }: { onNext: (data: UploadData) => void }) {
    return (
      <button type="button" onClick={() => void onNext(uploadData)}>
        Skip upload
      </button>
    );
  },
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

test("keeps the matching overlay when match fails", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
  );

  render(<App />);

  await user.click(screen.getByRole("button", { name: "Skip metadata" }));
  await user.click(screen.getByRole("button", { name: "Skip upload" }));

  await waitFor(() => {
    expect(screen.getByText("Matching Failed")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Go Back" })).toBeInTheDocument();
});
