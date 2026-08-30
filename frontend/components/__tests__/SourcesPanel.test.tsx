import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourcesPanel } from "@/components/SourcesPanel";

it("discloses sources, exclusions, normalization notes, and duplicates", async () => {
  const user = userEvent.setup();
  render(
    <SourcesPanel
      sources={[{ board_id: "42", board_name: "Deals", item_count: 147, partial: false, error: null }]}
      caveats={["12% of deals lack close dates"]}
      quality={{
        total_rows: 147,
        included_rows: 129,
        exclusions: { "deal:missing_close_date": 18 },
        normalization_notes: ["2 sector aliases normalized"],
        duplicate_records: [["deal-1", "deal-8"]],
      }}
    />,
  );

  expect(screen.getByText("Deals")).toBeVisible();
  expect(screen.getByText(/12% of deals lack close dates/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: /quality details/i }));
  expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent === "18 excluded: missing close date")).toBeVisible();
  expect(screen.getByText(/2 sector aliases normalized/i)).toBeVisible();
  expect(screen.getByText(/deal-1.*deal-8/i)).toBeVisible();
});
