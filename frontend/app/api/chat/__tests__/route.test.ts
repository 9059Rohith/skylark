import { NextRequest } from "next/server";
import { POST } from "@/app/api/chat/route";

it("forwards the upstream SSE body progressively without buffering it", async () => {
  vi.stubEnv("BACKEND_URL", "http://backend.test");
  const encoder = new TextEncoder();
  let releaseSecondChunk!: () => void;
  const secondChunk = new Promise<void>((resolve) => {
    releaseSecondChunk = resolve;
  });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('event: token\ndata: {"token":"first"}\n\n'));
          void secondChunk.then(() => {
            controller.enqueue(encoder.encode('event: done\ndata: {"intent":"pipeline_health"}\n\n'));
            controller.close();
          });
        },
      }),
      { headers: { "Content-Type": "text/event-stream" } },
    ),
  );
  const request = new NextRequest("http://frontend.test/api/chat", {
    method: "POST",
    body: JSON.stringify({ message: "Pipeline", session_id: "session" }),
    headers: { "Content-Type": "application/json" },
  });

  const response = await POST(request);
  const reader = response.body!.getReader();
  const first = await reader.read();

  expect(new TextDecoder().decode(first.value)).toContain('"token":"first"');
  expect(first.done).toBe(false);
  releaseSecondChunk();
  const second = await reader.read();
  expect(new TextDecoder().decode(second.value)).toContain("pipeline_health");
  expect(response.headers.get("X-Accel-Buffering")).toBe("no");
});
