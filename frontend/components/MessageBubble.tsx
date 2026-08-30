// Accessible message rendering is implemented in Task 4.
import { AlertTriangle, RotateCcw } from "lucide-react";
import type { ChatTurn } from "@/lib/types";
import { LeadershipUpdateCard } from "@/components/LeadershipUpdateCard";

type Props = { turn: ChatTurn; onRetry: (turn: ChatTurn) => void };

export function MessageBubble({ turn, onRetry }: Props) {
  return (
    <article className="turn" aria-label="Conversation turn">
      <div className="user-row">
        <p>{turn.prompt}</p>
        <span aria-hidden="true" className="avatar user-avatar">You</span>
      </div>
      <div className="assistant-row">
        <span aria-hidden="true" className="avatar signal-avatar">S</span>
        <div className="answer-copy">
          {turn.answer ? <p className="answer-text" aria-live="polite" aria-atomic="false">{turn.answer}</p> : null}
          {turn.status === "streaming" ? (
            <div className="thinking" role="status" aria-live="polite">
              <span className="thinking-dot" aria-hidden="true" />
              {turn.statusMessage ?? "Thinking through the evidence…"}
            </div>
          ) : null}
          {turn.caveats.length ? (
            <p className="inline-caveat">
              <AlertTriangle aria-hidden="true" size={17} /> {turn.caveats[0]}
            </p>
          ) : null}
          {turn.leadershipUpdate ? <LeadershipUpdateCard update={turn.leadershipUpdate} /> : null}
          {turn.error ? (
            <div className="turn-error" role="alert">
              <p>{turn.error.message}</p>
              <button type="button" className="text-button" onClick={() => onRetry(turn)}>
                <RotateCcw aria-hidden="true" size={15} /> Retry
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
