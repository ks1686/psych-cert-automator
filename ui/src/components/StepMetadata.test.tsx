import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import StepMetadata, {
  type MetadataFormData,
} from "@/components/StepMetadata";

const validMetadata: MetadataFormData = {
  title: "Ethics in School Psychology",
  date: "2026-07-21",
  endDate: "",
  isMultiDay: false,
  instructor: "Dr. Jane Smith",
  ceCredits: 3,
  ceTypes: { apa: true, nasp: false, ny: false },
  startTime: "09:00",
  endTime: "12:00",
  isVirtual: true,
  location: "",
};

test("disables Next when required fields are empty", () => {
  render(<StepMetadata onNext={vi.fn()} />);

  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("requires an end date for multi-day events", async () => {
  const user = userEvent.setup();
  render(
    <StepMetadata
      onNext={vi.fn()}
      initialData={{ ...validMetadata, isMultiDay: true }}
    />,
  );

  expect(screen.getByLabelText("End Date")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

  const endDate = screen.getByLabelText("End Date");
  await user.clear(endDate);
  await user.type(endDate, "2026-07-22");

  expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
});

test("requires a location for in-person events", async () => {
  const user = userEvent.setup();
  render(
    <StepMetadata
      onNext={vi.fn()}
      initialData={{ ...validMetadata, isVirtual: false }}
    />,
  );

  expect(screen.getByLabelText("In-person location")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

  await user.type(
    screen.getByLabelText("In-person location"),
    "Rutgers University",
  );

  expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
});

test("offers APA, NASP, and NY CE types without BCBA", () => {
  render(<StepMetadata onNext={vi.fn()} />);

  expect(screen.getByRole("checkbox", { name: "APA" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "NASP" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "NY" })).toBeInTheDocument();
  expect(
    screen.queryByRole("checkbox", { name: /BCBA/i }),
  ).not.toBeInTheDocument();
});
