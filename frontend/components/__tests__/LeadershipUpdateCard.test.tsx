import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeadershipUpdateCard } from "@/components/LeadershipUpdateCard";

const update = {
  headline_pipeline_value_inr: "48000000",
  sector_breakdown: [
    { sector: "Energy", deal_count: 18, pipeline_value_inr: "48000000" },
    { sector: "Manufacturing", deal_count: 4, pipeline_value_inr: "12000000" },
  ],
  notable_at_risk: [
    { record_type: "deal", record_id: "d1", name: "Greenfield Solar", reason: "No work order" },
    { record_type: "work_order", record_id: "w1", name: "North Plant", reason: "Missing completion date" },
  ],
  quality: {
    pipeline: { total_rows: 20, included_rows: 18, exclusions: {}, normalization_notes: [], duplicate_records: [] },
    sector: { total_rows: 20, included_rows: 18, exclusions: {}, normalization_notes: [], duplicate_records: [] },
    gaps: { total_rows: 20, included_rows: 18, exclusions: {}, normalization_notes: [], duplicate_records: [] },
    operational_risks: { total_rows: 12, included_rows: 10, exclusions: {}, normalization_notes: [], duplicate_records: [] },
  },
  quality_footnote: "2 rows excluded.",
  markdown: "# Leadership update (draft)\n\n**Headline pipeline:** INR 48,000,000",
};

it("copies the backend-authored Markdown and announces success", async () => {
  const user = userEvent.setup();
  const writeText = vi.spyOn(navigator.clipboard, "writeText");
  render(<LeadershipUpdateCard update={update} />);

  await user.click(screen.getByRole("button", { name: /copy as markdown/i }));

  expect(writeText).toHaveBeenCalledWith(update.markdown);
  expect(screen.getByRole("status")).toHaveTextContent("Copied");
});

it("announces an accessible failure when clipboard access is rejected", async () => {
  const user = userEvent.setup();
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValueOnce(new Error("permission denied"));
  render(<LeadershipUpdateCard update={update} />);

  await user.click(screen.getByRole("button", { name: /copy as markdown/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Could not copy the update");
  expect(screen.getByRole("button", { name: /copy as markdown/i })).toBeEnabled();
});

it("renders the complete leadership draft including all sectors, risks, and quality footnote", () => {
  render(<LeadershipUpdateCard update={update} />);
  const headline = screen.getByText("Headline pipeline").parentElement;
  expect(headline).not.toBeNull();
  expect(within(headline as HTMLElement).getByText("₹4,80,00,000")).toBeVisible();
  expect(screen.getByText(/Energy/)).toHaveTextContent("18 deals");
  expect(screen.getByText(/Manufacturing/)).toHaveTextContent("4 deals");
  expect(screen.getByText(/Greenfield Solar/)).toHaveTextContent("No work order");
  expect(screen.getByText(/North Plant/)).toHaveTextContent("Missing completion date");
  expect(screen.getByText("2 rows excluded.")).toBeVisible();
});

it("handles empty sections gracefully and uses unique accessible IDs per card", () => {
  const empty = { ...update, sector_breakdown: [], notable_at_risk: [] };
  render(<><LeadershipUpdateCard update={empty} /><LeadershipUpdateCard update={empty} /></>);
  expect(screen.getAllByText("No sector breakdown is available.")).toHaveLength(2);
  expect(screen.getAllByText("No notable risks were identified.")).toHaveLength(2);
  const regions = screen.getAllByRole("region", { name: "Leadership update" });
  expect(regions[0]?.getAttribute("aria-labelledby")).not.toBe(regions[1]?.getAttribute("aria-labelledby"));
});
