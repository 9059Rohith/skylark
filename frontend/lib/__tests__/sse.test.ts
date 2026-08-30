import { createSSEParser } from "@/lib/sse";

describe("createSSEParser", () => {
  it("reassembles fragmented chunks and multiline data", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));

    parser.push('event: status\ndata: {"event":"sta');
    parser.push('tus",\ndata: "stage":"fetch","message":"Reading boards"}\n\n');
    parser.finish();

    expect(events).toEqual([
      { event: "status", stage: "fetch", message: "Reading boards" },
    ]);
  });

  it("ignores comments, malformed JSON, and unknown event types safely", () => {
    const events: unknown[] = [];
    const parser = createSSEParser((event) => events.push(event));

    parser.push(': keepalive\n\nevent: mystery\ndata: {"event":"mystery"}\n\n');
    parser.push('event: token\ndata: not-json\n\n');
    parser.push('event: token\ndata: {"event":"token","token":"ready"}\n\n');
    parser.finish();

    expect(events).toEqual([{ event: "token", token: "ready" }]);
  });
});
