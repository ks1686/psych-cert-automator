import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import StepGenerate from "@/components/StepGenerate";
import type { MatchData } from "@/components/StepMatchReview";
import type { UploadData } from "@/components/StepUpload";

const matchData: MatchData = {
  matches: [
    {
      kind: "success",
      qualtrics_name: "Alex Rivera",
      zoom_name: "Alex Rivera",
      confidence: 1,
      candidates: null,
      attendance: {
        is_eligible: true,
        late_join: 0,
        early_leave: 0,
        gaps: 0,
        total_missed: 0,
        total_attended: 180,
        failure_reason: null,
      },
    },
  ],
  overrides: {},
  excludedNames: [],
  zoomParticipants: [
    {
      name: "Alex Rivera",
      first_join: "2026-07-21T09:00:00",
      last_leave: "2026-07-21T12:00:00",
      total_attended_minutes: 180,
      segments_count: 1,
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
  sessionStart: "2026-07-21T09:00:00",
  sessionEnd: "2026-07-21T12:00:00",
  zoomHost: null,
  zoomPath: "/tmp/zoom.xlsx",
};

const trainingMetadata = {
  title: "Ethics in School Psychology",
  date: "2026-07-21",
  end_date: null,
  instructor_name: "Dr. Jane Smith",
  ce_credits: 3,
  ce_types_offered: ["APA"],
  session_start: "09:00",
  session_end: "12:00",
  is_virtual: true,
  location: null,
};

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

afterEach(() => {
  vi.unstubAllGlobals();
});

async function selectOutputFolder(
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await user.click(
    screen.getByRole("button", { name: /Choose output folder/i }),
  );
  await waitFor(() => {
    expect(screen.getByText(/e2e-certs/)).toBeInTheDocument();
  });
}

test("keeps Generate disabled until an output folder is chosen", async () => {
  render(
    <StepGenerate
      onBack={vi.fn()}
      onReset={vi.fn()}
      matchData={matchData}
      trainingMetadata={trainingMetadata}
      uploadData={uploadData}
    />,
  );

  expect(
    screen.getByRole("button", { name: /Generate All Certificates/i }),
  ).toBeDisabled();
  expect(screen.getByText("No folder selected")).toBeInTheDocument();
});

test("shows Generate Again after a successful generation", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        certificates: [
          {
            name: "Alex Rivera",
            ce_type: "APA",
            filename: "Rivera_CECertificate_Smith_7.21.26.docx",
            path: "mock-token",
          },
        ],
        ineligible: [],
        conversion_warning: true,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);

  render(
    <StepGenerate
      onBack={vi.fn()}
      onReset={vi.fn()}
      matchData={matchData}
      trainingMetadata={trainingMetadata}
      uploadData={uploadData}
    />,
  );

  await selectOutputFolder(user);
  const generatePromise = user.click(
    screen.getByRole("button", { name: /Generate All Certificates/i }),
  );
  expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  await generatePromise;

  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /Generate Again/i }),
    ).toBeEnabled();
  });

  const generateCall = fetchMock.mock.calls.find((call) =>
    String(call[0]).includes("/api/generate"),
  );
  expect(generateCall).toBeDefined();
  const init = generateCall?.[1] as RequestInit;
  const body = JSON.parse(String(init.body)) as { output_dir: string };
  expect(body.output_dir).toBe("/tmp/e2e-certs");
  expect(
    screen.getByRole("button", { name: /Open output folder/i }),
  ).toBeEnabled();
});

test("counts only offered CE types, and still counts attendance", () => {
  const { unmount } = render(
    <StepGenerate
      onBack={vi.fn()}
      onReset={vi.fn()}
      matchData={matchData}
      trainingMetadata={{ ...trainingMetadata, ce_types_offered: ["NASP"] }}
      uploadData={uploadData}
    />,
  );
  expect(
    screen.getByText("No eligible certificates found. All participants are ineligible."),
  ).toBeInTheDocument();
  unmount();

  render(
    <StepGenerate
      onBack={vi.fn()}
      onReset={vi.fn()}
      matchData={{
        ...matchData,
        ceRequests: [
          {
            name_on_certificate: "Alex Rivera",
            email: "alex@example.com",
            ce_type: "Certificate of Attendance",
            license_number: null,
          },
        ],
      }}
      trainingMetadata={{ ...trainingMetadata, ce_types_offered: ["NASP"] }}
      uploadData={uploadData}
    />,
  );
  expect(screen.getByText("1 eligible certificate ready to generate.")).toBeInTheDocument();
});

test("surfaces generation HTTP errors instead of empty success", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "Zoom file not found" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  render(
    <StepGenerate
      onBack={vi.fn()}
      onReset={vi.fn()}
      matchData={matchData}
      trainingMetadata={trainingMetadata}
      uploadData={uploadData}
    />,
  );

  await selectOutputFolder(user);
  await user.click(
    screen.getByRole("button", { name: /Generate All Certificates/i }),
  );

  await waitFor(() => {
    expect(screen.getByText(/Generation failed \(400\)/i)).toBeInTheDocument();
  });
  expect(
    screen.getByRole("button", { name: /Generate All Certificates/i }),
  ).toBeEnabled();
});
