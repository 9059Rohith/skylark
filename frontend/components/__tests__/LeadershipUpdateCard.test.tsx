import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeadershipUpdateCard } from "@/components/LeadershipUpdateCard";

const update = {
  headline_pipeline_value_inr: "48000000",
  sector_breakdown: [{ sector: "Energy", deal_count: 18, pipeline_value_inr: "48000000" }],
  notable_at_risk: [{ record_type: "deal", record_id: "d1", name: "Greenfield Solar", reason: "No work order" }],
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
