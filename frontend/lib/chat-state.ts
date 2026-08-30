import type { ChatEvent, ChatTurn } from "@/lib/types";

export function initialTurn(id: string, prompt = ""): ChatTurn {
  return {
    id,
    prompt,
    answer: "",
    stage: null,
    statusMessage: null,
    status: "streaming",
    sources: [],
    caveats: [],
    quality: null,
    leadershipUpdate: null,
    intent: null,
    error: null,
  };
}

export function reduceEvent(turn: ChatTurn, event: ChatEvent): ChatTurn {
  switch (event.event) {
    case "status":
      return { ...turn, stage: event.stage, statusMessage: event.message, status: "streaming" };
    case "sources":
      return { ...turn, sources: event.sources };
    case "caveats":
      return { ...turn, caveats: event.caveats, quality: event.quality };
    case "leadership_update":
      return { ...turn, leadershipUpdate: event.leadership_update };
    case "token":
      return { ...turn, answer: turn.answer + event.token, status: "streaming" };
    case "done":
      return {
        ...turn,
        status: "complete",
        stage: null,
        statusMessage: null,
        intent: event.intent,
      };
    case "error":
      return {
        ...turn,
        status: "error",
        stage: null,
        statusMessage: null,
        error: { code: event.code, message: event.message },
      };
  }
}
