import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import StepMatchReview, {
  type MatchData,
} from "@/components/StepMatchReview";

const initialData: MatchData = {
  matches: [
    {
      kind: "success",
      qualtrics_name: "Jessica Benas",
      zoom_name: "Jessica Benas",
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
      name: "Jessica Benas",
      first_join: "2026-07-21T09:00:00",
      last_leave: "2026-07-21T12:00:00",
      total_attended_minutes: 180,
      segments_count: 1,
    },
  ],
  ceRequests: [
    {
      name_on_certificate: "Jessica Benas",
      email: "jessica@example.com",
      ce_type: "APA",
      license_number: null,
    },
  ],
  sessionStart: "2026-07-21T09:00:00",
  sessionEnd: "2026-07-21T12:00:00",
  zoomHost: "Jessica Benas",
  zoomPath: "/tmp/zoom.xlsx",
};

test("pre-excludes the Zoom host and allows including them", async () => {
  const user = userEvent.setup();
  const onNext = vi.fn();
  render(
    <StepMatchReview
      initialData={initialData}
      onBack={vi.fn()}
      onNext={onNext}
    />,
  );

  const hostCheckbox = screen.getByRole("checkbox", { name: "Host" });
  expect(hostCheckbox).toBeChecked();

  await user.click(hostCheckbox);
  await user.click(screen.getByRole("button", { name: "Next" }));

  expect(onNext).toHaveBeenCalledWith(
    expect.objectContaining({ excludedNames: [] }),
  );
});
