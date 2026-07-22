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

function sseBody(events: unknown[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("shows Generate Again after a successful generation", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(
      sseBody([
        {
          type: "progress",
          current: 1,
          total: 1,
          success_count: 1,
          failure_count: 0,
        },
        {
          type: "complete",
          certificates: [
            {
              name: "Alex Rivera",
              ce_type: "APA",
              filename: "Rivera_CECertificate_Smith_2026-07-21.docx",
              path: "/tmp/Rivera_CECertificate_Smith_2026-07-21.docx",
            },
          ],
          ineligible: [],
          conversion_warning: true,
        },
      ]),
      {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
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

  await user.click(
    screen.getByRole("button", { name: /Generate All Certificates/i }),
  );

  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /Generate Again/i }),
    ).toBeEnabled();
  });
});
