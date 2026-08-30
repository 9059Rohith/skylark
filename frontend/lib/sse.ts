import { z } from "zod";
import type { ChatEvent } from "@/lib/types";

const qualitySchema = z.object({
  total_rows: z.number().int().nonnegative(),
  included_rows: z.number().int().nonnegative(),
  exclusions: z.record(z.string(), z.number().int().nonnegative()),
  normalization_notes: z.array(z.string()),
  duplicate_records: z.array(z.tuple([z.string(), z.string()])),
}).refine((quality) => quality.included_rows <= quality.total_rows);

const sourceSchema = z.object({
  board_id: z.string(),
  board_name: z.string(),
  item_count: z.number().int().nonnegative(),
  partial: z.boolean(),
  error: z.string().nullable(),
});

const amountSchema = z.union([
  z.number().finite(),
  z.string().regex(/^-?\d+(?:\.\d+)?$/),
]);

const sectorSummarySchema = z.object({
  sector: z.string(),
  deal_count: z.number().int().nonnegative(),
  pipeline_value_inr: amountSchema,
});

const atRiskSchema = z.object({
  record_type: z.string(),
  record_id: z.string().nullable(),
  name: z.string().nullable(),
  reason: z.string(),
});

const leadershipSchema = z.object({
  headline_pipeline_value_inr: amountSchema,
  sector_breakdown: z.array(sectorSummarySchema),
  notable_at_risk: z.array(atRiskSchema),
  quality: z.object({
    pipeline: qualitySchema,
    sector: qualitySchema,
    gaps: qualitySchema,
    operational_risks: qualitySchema,
  }),
  quality_footnote: z.string(),
  markdown: z.string(),
});

const chatEventSchema = z.discriminatedUnion("event", [
  z.object({ event: z.literal("status"), stage: z.string(), message: z.string() }),
  z.object({ event: z.literal("sources"), sources: z.array(sourceSchema) }),
  z.object({ event: z.literal("caveats"), caveats: z.array(z.string()), quality: qualitySchema.nullable() }),
  z.object({ event: z.literal("leadership_update"), leadership_update: leadershipSchema }),
  z.object({ event: z.literal("token"), token: z.string() }),
  z.object({ event: z.literal("done"), session_id: z.string(), intent: z.string() }),
  z.object({ event: z.literal("error"), code: z.string(), message: z.string() }),
]);

const invalidStream: ChatEvent = {
  event: "error",
  code: "invalid_stream",
  message: "The analysis stream contained invalid data.",
};

const interruptedStream: ChatEvent = {
  event: "error",
  code: "stream_interrupted",
  message: "The analysis stream ended before completion.",
};

export function parseChatEvent(value: unknown): ChatEvent | null {
  const result = chatEventSchema.safeParse(value);
  return result.success ? result.data as ChatEvent : null;
}

export function createSSEParser(onEvent: (event: ChatEvent) => void) {
  let buffer = "";
  let terminal = false;

  const emit = (event: ChatEvent) => {
    if (terminal) return;
    onEvent(event);
    if (event.event === "done" || event.event === "error") terminal = true;
  };

  const dispatch = (block: string) => {
    if (terminal) return;
    const lines = block.split(/\r?\n/);
    const declaredEvent = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const dataLines = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (!dataLines.length) return;

    let parsed: unknown;
    for (const candidate of [dataLines.join("\n"), dataLines.join("")]) {
      try {
        parsed = JSON.parse(candidate);
        break;
      } catch {
        parsed = undefined;
      }
    }
    const event = parseChatEvent(parsed);
    if (!event || (declaredEvent && declaredEvent !== event.event)) {
      emit(invalidStream);
      return;
    }
    emit(event);
  };

  const drain = () => {
    let boundary = buffer.search(/\r?\n\r?\n/);
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0] ?? "\n\n";
      buffer = buffer.slice(boundary + separator.length);
      dispatch(block);
      boundary = buffer.search(/\r?\n\r?\n/);
    }
  };

  return {
    push(chunk: string) {
      if (terminal) return;
      buffer += chunk;
      drain();
    },
    finish() {
      if (terminal) return;
      if (buffer.trim()) dispatch(buffer);
      buffer = "";
      if (!terminal) emit(interruptedStream);
    },
  };
}

export async function consumeSSE(
  response: Response,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const parser = createSSEParser(onEvent);
  if (!response.body) {
    parser.finish();
    return;
  }
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
