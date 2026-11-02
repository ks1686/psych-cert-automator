import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import StepMetadata, {
  ceCreditsError,
  type MetadataFormData,
} from "@/components/StepMetadata";

const validMetadata: MetadataFormData = {
  title: "Ethics in School Psychology",
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

test("explains session times are printed and used for attendance", () => {
  render(<StepMetadata onNext={vi.fn()} />);

  expect(
    screen.getByText(/printed on certificates/i),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/attendance is checked against/i),
  ).toBeInTheDocument();
});

test("accepts quarter-step CE credits and rejects other fractions", () => {
  expect(ceCreditsError(1.5)).toBeNull();
  expect(ceCreditsError(0.25)).toBeNull();
  expect(ceCreditsError(3)).toBeNull();
  expect(ceCreditsError(1.3)).toMatch(/steps of 0.25/);
  expect(ceCreditsError(0)).toMatch(/greater than 0/);
  expect(ceCreditsError(101)).toMatch(/at most 100/);
});

test("enables Next for 1.5 CE credits", () => {
  render(
    <StepMetadata
      onNext={vi.fn()}
      initialData={{ ...validMetadata, ceCredits: 1.5 }}
    />,
  );

  expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
});

test("offers APA, NASP, NY, and NBCC CE types without BCBA", () => {
  render(<StepMetadata onNext={vi.fn()} />);

  expect(screen.getByRole("checkbox", { name: "APA" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "NASP" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "NY" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "NBCC" })).toBeInTheDocument();
  expect(
    screen.queryByRole("checkbox", { name: /BCBA/i }),
  ).not.toBeInTheDocument();
});
