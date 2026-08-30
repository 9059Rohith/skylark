import { createSSEParser, parseChatEvent } from "@/lib/sse";

const quality = {
  total_rows: 2,
  included_rows: 1,
  exclusions: { missing_date: 1 },
  normalization_notes: ["Energy alias normalized"],
  duplicate_records: [["a", "b"]],
};

const leadership = {
  headline_pipeline_value_inr: "100000",
  sector_breakdown: [{ sector: "Energy", deal_count: 1, pipeline_value_inr: "100000" }],
  notable_at_risk: [{ record_type: "deal", record_id: "d1", name: "Solar", reason: "No work order" }],
  quality: { pipeline: quality, sector: quality, gaps: quality, operational_risks: quality },
  quality_footnote: "One row excluded.",
  markdown: "# Leadership update",
};

describe("parseChatEvent", () => {
  it("structurally accepts all seven event variants", () => {
    const events = [
      { event: "status", stage: "fetch", message: "Reading boards" },
      { event: "sources", sources: [{ board_id: "1", board_name: "Deals", item_count: 2, partial: false, error: null }] },
      { event: "caveats", caveats: ["One missing date"], quality },
      { event: "leadership_update", leadership_update: leadership },
      { event: "token", token: "Ready" },
      { event: "done", session_id: "session", intent: "pipeline_health" },
      { event: "error", code: "upstream", message: "Unavailable" },
    ];
    expect(events.map(parseChatEvent)).toEqual(events);
  });

  it.each([
    { event: "status", stage: 4, message: "Reading" },
    { event: "sources", sources: [{ board_id: "1", board_name: "Deals", item_count: -1, partial: false }] },
    { event: "caveats", caveats: "not-an-array", quality },
    { event: "caveats", caveats: [], quality: { ...quality, included_rows: 3 } },
    { event: "leadership_update", leadership_update: { ...leadership, sector_breakdown: [{ sector: "Energy" }] } },
    { event: "leadership_update", leadership_update: { ...leadership, headline_pipeline_value_inr: "not-a-number" } },
    { event: "token", token: 42 },
    { event: "done", intent: "pipeline_health" },
    { event: "error", code: "upstream" },
  ])("rejects malformed nested payload %#", (payload) => {
    expect(parseChatEvent(payload)).toBeNull();
  });
});

describe("createSSEParser", () => {
  it("reassembles fragmented CRLF chunks and valid multiline data", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));
    parser.push('event: status\r\ndata: {"event":"status",\r\ndata: "stage":"fet');
    parser.push('ch",\r\ndata: "message":"Reading boards"}\r\n\r\n');
    parser.push('event: done\r\ndata: {"event":"done","session_id":"s","intent":"pipeline_health"}\r\n\r\n');
    parser.finish();
    expect(events).toEqual([
      { event: "status", stage: "fetch", message: "Reading boards" },
      { event: "done", session_id: "s", intent: "pipeline_health" },
    ]);
  });

  it("turns malformed nested data into one safe terminal error and ignores later events", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));
    parser.push('event: sources\ndata: {"event":"sources","sources":[{"board_id":"1","item_count":-2}]}\n\n');
    parser.push('event: token\ndata: {"event":"token","token":"must not render"}\n\n');
    parser.finish();
    expect(events).toEqual([{ event: "error", code: "invalid_stream", message: "The analysis stream contained invalid data." }]);
  });

  it("turns malformed JSON into one safe visible terminal error", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));
    parser.push("event: token\ndata: {definitely-not-json}\n\n");
    parser.finish();
    expect(events).toEqual([{ event: "error", code: "invalid_stream", message: "The analysis stream contained invalid data." }]);
  });

  it("reports empty and clean EOF streams without a terminal event as interrupted", () => {
    const empty: unknown[] = [];
    createSSEParser((event) => empty.push(event)).finish();
    const truncated: unknown[] = [];
    const parser = createSSEParser((event) => truncated.push(event));
    parser.push('event: token\ndata: {"event":"token","token":"Partial answer"}\n\n');
    parser.finish();
    const interrupted = { event: "error", code: "stream_interrupted", message: "The analysis stream ended before completion." };
    expect(empty).toEqual([interrupted]);
    expect(truncated).toEqual([{ event: "token", token: "Partial answer" }, interrupted]);
  });

  it("accepts exactly one terminal event and rejects post-terminal events", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));
    parser.push('event: done\ndata: {"event":"done","session_id":"s","intent":"pipeline_health"}\n\n');
    parser.push('event: error\ndata: {"event":"error","code":"late","message":"Late"}\n\n');
    parser.push('event: token\ndata: {"event":"token","token":"Late token"}\n\n');
    parser.finish();
    expect(events).toEqual([{ event: "done", session_id: "s", intent: "pipeline_health" }]);
  });
});
