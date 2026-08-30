import { initialTurn, reduceEvent } from "@/lib/chat-state";

const quality = {
  total_rows: 147,
  included_rows: 129,
  exclusions: { "deal:missing_close_date": 18 },
  normalization_notes: ["2 sector aliases normalized"],
  duplicate_records: [["deal-1", "deal-8"]] as [string, string][],
};

describe("reduceEvent", () => {
  it("progressively accumulates tokens and retains complete provenance", () => {
    const events = [
      { event: "status" as const, stage: "fetch", message: "Reading Deals" },
      {
        event: "sources" as const,
        sources: [{ board_id: "42", board_name: "Deals", item_count: 147, partial: false, error: null }],
      },
      { event: "caveats" as const, caveats: ["12% lack close dates"], quality },
      { event: "token" as const, token: "₹4.8 Cr " },
      { event: "token" as const, token: "qualified pipeline." },
      { event: "done" as const, session_id: "id", intent: "pipeline_health" },
    ];

    const result = events.reduce(reduceEvent, initialTurn("turn-1"));

    expect(result.answer).toBe("₹4.8 Cr qualified pipeline.");
    expect(result.sources[0]?.board_name).toBe("Deals");
    expect(result.quality).toEqual(quality);
    expect(result.caveats).toEqual(["12% lack close dates"]);
    expect(result.status).toBe("complete");
  });

  it("recovers from an error without losing already received sources and caveats", () => {
    let turn = reduceEvent(initialTurn("turn-2"), {
      event: "sources",
      sources: [{ board_id: "7", board_name: "Work Orders", item_count: 12, partial: true, error: "rate limited" }],
    });
    turn = reduceEvent(turn, {
      event: "caveats",
      caveats: ["Partial Work Orders data"],
      quality: null,
    });
    turn = reduceEvent(turn, {
      event: "error",
      code: "upstream",
      message: "Live data could not be fully loaded.",
    });

    expect(turn.status).toBe("error");
    expect(turn.error).toMatchObject({ code: "upstream" });
    expect(turn.sources).toHaveLength(1);
    expect(turn.caveats).toEqual(["Partial Work Orders data"]);
  });
});
