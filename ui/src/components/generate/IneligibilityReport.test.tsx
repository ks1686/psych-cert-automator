import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { IneligibilityReport } from "@/components/generate/IneligibilityReport";

test("keeps filter chips when a status filter matches no rows", async () => {
  const user = userEvent.setup();
  render(
    <IneligibilityReport
      entries={[
        {
          name: "Alex Rivera",
          status: "Not Found",
          reason: "No Zoom match",
        },
      ]}
    />,
  );

  expect(screen.getByText("Ineligibility Report (1 total)")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Ambiguous/i }));
  expect(screen.getByText("Ineligibility Report (1 total)")).toBeInTheDocument();
  expect(screen.getByText(/No rows match this filter/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Not Found/i })).toBeInTheDocument();
});
