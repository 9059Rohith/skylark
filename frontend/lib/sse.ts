import type { ChatEvent } from "@/lib/types";

const EVENT_NAMES = new Set([
  "status",
  "sources",
  "caveats",
  "leadership_update",
  "token",
  "done",
  "error",
]);

function isChatEvent(value: unknown): value is ChatEvent {
  return Boolean(
    value &&
      typeof value === "object" &&
      "event" in value &&
      typeof value.event === "string" &&
      EVENT_NAMES.has(value.event),
  );
}

export function createSSEParser(onEvent: (event: ChatEvent) => void) {
  let buffer = "";

  const dispatch = (block: string) => {
    const dataLines = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (!dataLines.length) return;

    for (const candidate of [dataLines.join("\n"), dataLines.join("")]) {
      try {
        const parsed: unknown = JSON.parse(candidate);
        if (isChatEvent(parsed)) onEvent(parsed);
        return;
      } catch {
        // Some proxies split a JSON object across multiple data lines.
      }
    }
  };

  const drain = () => {
    let boundary = buffer.search(/\r?\n\r?\n/);
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      const match = buffer.slice(boundary).match(/^\r?\n\r?\n/);
      buffer = buffer.slice(boundary + (match?.[0].length ?? 2));
      dispatch(block);
      boundary = buffer.search(/\r?\n\r?\n/);
    }
  };

  return {
    push(chunk: string) {
      buffer += chunk;
      drain();
    },
    finish() {
      if (buffer.trim()) dispatch(buffer);
      buffer = "";
    },
  };
}

export async function consumeSSE(
  response: Response,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  if (!response.body) throw new Error("The response stream was empty.");
  const parser = createSSEParser(onEvent);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode());
    parser.finish();
  } finally {
    reader.releaseLock();
  }
}
