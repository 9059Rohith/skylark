import { render, screen, waitFor } from "@testing-library/react";
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
    .mockResolvedValueOnce(sseResponse(['event: token\ndata: {"event":"token","token":"Recovered."}\n\n']));
  render(<ChatWindow />);

  await user.type(screen.getByRole("textbox"), "Show pipeline");
  await user.click(screen.getByRole("button", { name: /send message/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Monday is temporarily unavailable.");

  await user.click(screen.getByRole("button", { name: /retry/i }));
  expect(await screen.findByText("Recovered.")).toBeVisible();
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
