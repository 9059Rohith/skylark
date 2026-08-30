import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatWindow } from "@/components/ChatWindow";

function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

const releaseArchetypes = [
  ["pipeline_health", "How healthy is our pipeline?", "Pipeline answer."],
  ["revenue", "What revenue did we win?", "Revenue answer."],
  ["won_without_work_orders", "Which won deals have no work orders?", "Gap answer."],
  ["work_order_completion", "What is average work order completion time?", "Completion answer."],
  ["data_quality", "How many deals are missing close dates?", "Quality answer."],
] as const;

it("shows an honest submission identity without unfinished navigation", () => {
  render(<ChatWindow />);

  expect(screen.getByText("Rohith")).toBeVisible();
  expect(screen.getByText("Project author")).toBeVisible();
  expect(screen.queryByText("Arjun Rao")).not.toBeInTheDocument();
  expect(screen.queryByText("Alerts")).not.toBeInTheDocument();
  expect(screen.queryByText("Settings")).not.toBeInTheDocument();
});

it.each(releaseArchetypes)("renders the mocked %s archetype through the chat UI", async (intent, prompt, answer) => {
  const user = userEvent.setup();
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([
    'event: sources\ndata: {"event":"sources","sources":[{"board_id":"101","board_name":"Deals","item_count":2,"partial":false,"error":null}]}\n\n',
    `event: token\ndata: ${JSON.stringify({ event: "token", token: answer })}\n\n`,
    `event: done\ndata: ${JSON.stringify({ event: "done", session_id: "x", intent })}\n\n`,
  ]));
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), prompt);
  await user.click(screen.getByRole("button", { name: /send message/i }));

  expect(await screen.findByText(answer)).toBeVisible();
  expect(screen.getByRole("heading", { name: "Deals" })).toBeVisible();
  const body = JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string);
  expect(body.message).toBe(prompt);
});

it("renders the mocked leadership-update archetype as a reviewable draft", async () => {
  const user = userEvent.setup();
  const leadership = {
    headline_pipeline_value_inr: "21000000",
    sector_breakdown: [{ sector: "Energy", deal_count: 1, pipeline_value_inr: "20000000" }],
    notable_at_risk: [],
    quality: {
      pipeline: { total_rows: 2, included_rows: 2, exclusions: {}, normalization_notes: [], duplicate_records: [] },
      sector: { total_rows: 2, included_rows: 2, exclusions: {}, normalization_notes: [], duplicate_records: [] },
      gaps: { total_rows: 3, included_rows: 2, exclusions: { not_won: 1 }, normalization_notes: [], duplicate_records: [] },
      operational_risks: { total_rows: 1, included_rows: 1, exclusions: {}, normalization_notes: [], duplicate_records: [] },
    },
    quality_footnote: "All headline rows were usable.",
    markdown: "# Leadership update (draft)",
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([
    `event: leadership_update\ndata: ${JSON.stringify({ event: "leadership_update", leadership_update: leadership })}\n\n`,
    'event: token\ndata: {"event":"token","token":"Leadership draft ready."}\n\n',
    'event: done\ndata: {"event":"done","session_id":"x","intent":"leadership_update"}\n\n',
  ]));
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), "Draft the weekly leadership update");
  await user.click(screen.getByRole("button", { name: /send message/i }));

  expect(await screen.findByRole("region", { name: "Leadership update" })).toBeVisible();
  expect(screen.getByRole("button", { name: /copy as markdown/i })).toBeEnabled();
});

it("streams a turn, shows progress, preserves session continuity, and restores focus", async () => {
  const user = userEvent.setup();
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      sseResponse([
        'event: status\ndata: {"event":"status","stage":"fetch","message":"Reading live boards"}\n\n',
        'event: token\ndata: {"event":"token","token":"₹4.8 Cr pipeline."}\n\n',
        'event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n',
      ]),
    )
    .mockResolvedValueOnce(
      sseResponse(['event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n']),
    );
  render(<ChatWindow />);
  const input = screen.getByRole("textbox", { name: /ask skylark signal/i });

  await user.type(input, "How is pipeline for Energy?");
  await user.keyboard("{Enter}");

  expect(await screen.findByText("₹4.8 Cr pipeline.")).toBeVisible();
  await waitFor(() => expect(input).toHaveFocus());
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();

  await user.type(input, "Break that down by sector");
  await user.keyboard("{Enter}");
  const firstBody = JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string);
  const secondBody = JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string);
  expect(secondBody.session_id).toBe(firstBody.session_id);
  expect(secondBody.session_id).toMatch(/^[0-9a-f-]{36}$/);
});

it("announces streaming errors and allows a retry without losing the failed prompt", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      sseResponse(['event: error\ndata: {"event":"error","code":"upstream","message":"Monday is temporarily unavailable."}\n\n']),
    )
    .mockResolvedValueOnce(sseResponse([
      'event: token\ndata: {"event":"token","token":"Recovered."}\n\n',
      'event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n',
    ]));
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), "Show pipeline");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Monday is temporarily unavailable.");

  await user.click(screen.getByRole("button", { name: /retry/i }));
  expect(await screen.findByText("Recovered.")).toBeVisible();
  expect(screen.queryByText(/ended before completion/i)).not.toBeInTheDocument();
});

it("rotates the session identifier when starting a new conversation", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    sseResponse(['event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n']),
  );
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), "First thread");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  await user.click(screen.getByRole("button", { name: /^new conversation/i }));
  await user.type(screen.getByRole("textbox"), "Fresh thread");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

  const first = JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string);
  const second = JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string);
  expect(second.session_id).not.toBe(first.session_id);
});

it("uses a modal evidence dialog with focus containment, Escape close, and focus restore", async () => {
  const user = userEvent.setup();
  render(<ChatWindow />);
  const trigger = screen.getByRole("button", { name: /open evidence panel/i });
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("dialog", { name: /evidence and data quality/i })).not.toBeInTheDocument();
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", { name: /evidence and data quality/i });
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("button", { name: /close evidence panel/i })).toHaveFocus();
  await user.tab();
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  await user.tab({ shift: true });
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: /evidence and data quality/i })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute("aria-expanded", "false");

  await user.click(trigger);
  const backdrop = document.querySelector(".drawer-backdrop");
  expect(backdrop).toBeInstanceOf(HTMLDivElement);
  expect(backdrop).toHaveAttribute("aria-hidden", "true");
  expect(backdrop).toHaveAttribute("tabindex", "-1");
  await user.click(backdrop as HTMLElement);
  expect(screen.queryByRole("dialog", { name: /evidence and data quality/i })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("keeps the transcript out of the live region while announcing new assistant text", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([
    'event: token\ndata: {"event":"token","token":"A narrow announcement."}\n\n',
    'event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n',
  ]));
  render(<ChatWindow />);
  expect(screen.getByTestId("transcript")).not.toHaveAttribute("aria-live");
  await user.type(screen.getByRole("textbox"), "Question");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  expect(await screen.findByText("A narrow announcement.")).toHaveAttribute("aria-live", "polite");
});

it("renders a material caveat only once inside the conversation turn", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([
    'event: caveats\ndata: {"event":"caveats","caveats":["1 row excluded."],"quality":{"total_rows":2,"included_rows":1,"exclusions":{"invalid_currency":1},"normalization_notes":[],"duplicate_records":[]}}\n\n',
    'event: token\ndata: {"event":"token","token":"Answer. Material caveat: 1 row excluded."}\n\n',
    'event: done\ndata: {"event":"done","session_id":"x","intent":"pipeline_health"}\n\n',
  ]));
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), "Question");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  const turn = await screen.findByRole("article", { name: /conversation turn/i });
  await waitFor(() => expect(within(turn).getAllByText(/1 row excluded/)).toHaveLength(1));
});

it("retains partial evidence and shows a safe error for a truncated stream", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(sseResponse([
    'event: sources\ndata: {"event":"sources","sources":[{"board_id":"1","board_name":"Deals","item_count":2,"partial":false,"error":null}]}\n\n',
    'event: token\ndata: {"event":"token","token":"Partial result"}\n\n',
  ]));
  render(<ChatWindow />);
  await user.type(screen.getByRole("textbox"), "Question");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  expect(await screen.findByText("Partial result")).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent("ended before completion");
  await user.click(screen.getByRole("button", { name: /open evidence panel/i }));
  expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Deals" })).toBeVisible();
});
