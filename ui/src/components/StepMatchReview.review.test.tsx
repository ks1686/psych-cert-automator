import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import StepMatchReview, {
  matchNeedsReview,
  type MatchData,
  type MatchEntryWire,
} from "@/components/StepMatchReview";

const fuzzy: MatchEntryWire = {
  kind: "success",
  qualtrics_name: "Sam Rivera",
  zoom_name: "Sam",
  confidence: 0.7,
  needs_review: true,
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
};

const data: MatchData = {
  matches: [fuzzy],
  overrides: {},
  excludedNames: [],
  zoomParticipants: [
    {
      name: "Sam",
      first_join: "2026-11-02T09:00:00",
      last_leave: "2026-11-02T12:00:00",
      total_attended_minutes: 180,
      segments_count: 1,
    },
  ],
  ceRequests: [
    {
      name_on_certificate: "Sam Rivera",
      email: "sam.rivera@example.test",
      ce_type: "APA",
      license_number: null,
    },
  ],
  sessionStart: "2026-11-02T08:30:00",
  sessionEnd: "2026-11-02T12:15:00",
  startTime: "09:00",
  endTime: "12:00",
  zoomHost: null,
  zoomPath: "/tmp/zoom.xlsx",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a partial match is flagged and is not confirmed without a click", async () => {
  const user = userEvent.setup();
  const onNext = vi.fn();
  render(<StepMatchReview initialData={data} onBack={vi.fn()} onNext={onNext} />);

  expect(screen.getByText("1 need review")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Include Sam Rivera" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next" }));

  expect(onNext).toHaveBeenCalledWith(
    expect.objectContaining({ overrides: {} }),
  );
  expect(matchNeedsReview(onNext.mock.calls[0][0].matches[0])).toBe(true);
});

test("Include sends the match back as an override with the typed session times", async () => {
  const user = userEvent.setup();
  const onNext = vi.fn();
  const confirmed = { ...fuzzy, confidence: 1, needs_review: false };
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ matches: [confirmed] }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<StepMatchReview initialData={data} onBack={vi.fn()} onNext={onNext} />);

  await user.click(screen.getByRole("button", { name: "Include Sam Rivera" }));
  await user.click(screen.getByRole("button", { name: "Next" }));

  const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
  expect(body.overrides).toEqual({ "Sam Rivera": "Sam" });
  expect(body.start_time).toBe("09:00");
  expect(body.end_time).toBe("12:00");
  expect(onNext).toHaveBeenCalledWith(
    expect.objectContaining({ overrides: { "Sam Rivera": "Sam" }, matches: [confirmed] }),
  );
});
