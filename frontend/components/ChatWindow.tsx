"use client";

import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  ChevronDown,
  Database,
  Home,
  MessageSquare,
  PanelRightOpen,
  Plus,
  Send,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import { MessageBubble } from "@/components/MessageBubble";
import { SourcesPanel } from "@/components/SourcesPanel";
import { initialTurn, reduceEvent } from "@/lib/chat-state";
import { createNewSessionId, getOrCreateSessionId } from "@/lib/session";
import { consumeSSE } from "@/lib/sse";
import type { ChatTurn } from "@/lib/types";

const SUGGESTIONS = [
  "How’s our pipeline for Energy this quarter?",
  "Which won deals don’t have a work order?",
  "Draft a leadership update",
];

function SignalMark() {
  return <span className="signal-mark" aria-hidden="true">S</span>;
}

export function ChatWindow() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const evidenceTriggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionRef = useRef<string | null>(null);
  const activeTurn = turns.at(-1);

  useEffect(() => {
    sessionRef.current = getOrCreateSessionId(window.localStorage);
    inputRef.current?.focus();
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!turns.length) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    requestAnimationFrame(() => endRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "end",
    }));
  }, [turns.length, activeTurn?.status, activeTurn?.stage]);

  useEffect(() => {
    if (!evidenceOpen) return;
    dialogRef.current?.querySelector<HTMLElement>("[data-dialog-close]")?.focus();
  }, [evidenceOpen]);

  const updateTurn = useCallback((turnId: string, update: (turn: ChatTurn) => ChatTurn) => {
    setTurns((current) => current.map((turn) => turn.id === turnId ? update(turn) : turn));
  }, []);

  const sendPrompt = useCallback(async (prompt: string) => {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || isSending) return;
    const turnId = crypto.randomUUID();
    const nextTurn = initialTurn(turnId, cleanPrompt);
    setTurns((current) => [...current, nextTurn]);
    setDraft("");
    setIsSending(true);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const sessionId = sessionRef.current ?? getOrCreateSessionId(window.localStorage);
      sessionRef.current = sessionId;
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ message: cleanPrompt, session_id: sessionId }),
        signal: controller.signal,
      });
      if (!response.ok || !response.headers.get("content-type")?.includes("text/event-stream")) {
        throw new Error(response.status === 429
          ? "Skylark Signal is at capacity. Please try again shortly."
          : "The live analysis service is unavailable right now.");
      }
      await consumeSSE(response, (event) => updateTurn(turnId, (turn) => reduceEvent(turn, event)));
      updateTurn(turnId, (turn) => turn.status === "streaming"
        ? { ...turn, status: "complete", stage: null, statusMessage: null }
        : turn);
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : "The request could not be completed.";
      updateTurn(turnId, (turn) => ({
        ...turn,
        status: "error",
        stage: null,
        statusMessage: null,
        error: { code: "network", message },
      }));
    } finally {
      setIsSending(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [isSending, updateTurn]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void sendPrompt(draft);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!isSending) void sendPrompt(draft);
    }
  }

  function startNewConversation() {
    abortRef.current?.abort();
    sessionRef.current = createNewSessionId(window.localStorage);
    setTurns([]);
    setDraft("");
    setIsSending(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  const closeEvidence = useCallback(() => {
    setEvidenceOpen(false);
    evidenceTriggerRef.current?.focus();
  }, []);

  function handleDialogKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeEvidence();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []).filter((element) => !element.hasAttribute("hidden"));
    if (!focusable.length) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (focusable.length === 1 || (event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first)?.focus();
    }
  }

  return (
    <div className="app-shell">
      <aside className="nav-rail" aria-label="Primary navigation">
        <div className="brand">
          <SignalMark />
          <div><strong>Skylark Signal</strong><span>Live business intelligence</span></div>
        </div>
        <button className="new-conversation" type="button" onClick={startNewConversation}>
          <Plus aria-hidden="true" size={17} /> New conversation
        </button>
        <nav>
          <a href="#conversation" aria-current="page"><Home aria-hidden="true" size={18} /> Home</a>
          <span className="nav-label"><Bell aria-hidden="true" size={18} /> Alerts <span className="nav-dot" /></span>
          <a href="#evidence"><Database aria-hidden="true" size={18} /> Data</a>
          <span className="nav-label"><Settings aria-hidden="true" size={18} /> Settings</span>
        </nav>
        <div className="recent">
          <h2>Founder prompts</h2>
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => void sendPrompt(suggestion)}>
              <MessageSquare aria-hidden="true" size={15} /><span>{suggestion}</span>
            </button>
          ))}
        </div>
        <div className="profile">
          <span className="avatar">AR</span>
          <div><strong>Arjun Rao</strong><span>Founder</span></div>
          <ChevronDown aria-hidden="true" size={17} />
        </div>
      </aside>

      <main className="conversation" id="conversation">
        <header className="conversation-header">
          <div><MessageSquare aria-hidden="true" size={18} /><h1>Conversation</h1></div>
          <span className="live-indicator"><i aria-hidden="true" /> Live</span>
          <button
            ref={evidenceTriggerRef}
            type="button"
            className="mobile-icon-button"
            aria-label="Open evidence panel"
            aria-controls="mobile-evidence-dialog"
            aria-expanded={evidenceOpen}
            onClick={() => setEvidenceOpen(true)}
          >
            <PanelRightOpen aria-hidden="true" />
          </button>
        </header>

        <div className="conversation-body" data-testid="transcript">
          {!turns.length ? (
            <section className="empty-state">
              <SignalMark />
              <h2>Ask the business. See the evidence.</h2>
              <p>Pipeline, delivery, cross-board gaps, and data quality—answered from your live monday.com boards.</p>
              <div className="suggestion-list">
                {SUGGESTIONS.map((suggestion) => (
                  <button key={suggestion} type="button" onClick={() => void sendPrompt(suggestion)}>{suggestion}</button>
                ))}
              </div>
            </section>
          ) : turns.map((turn) => <MessageBubble key={turn.id} turn={turn} onRetry={(failed) => void sendPrompt(failed.prompt)} />)}
          <div ref={endRef} />
        </div>

        <div className="composer-wrap">
          <form className="composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="chat-input">Ask Skylark Signal</label>
            <textarea
              id="chat-input"
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about pipeline, delivery, or data quality…"
              rows={2}
              maxLength={4000}
              disabled={isSending}
            />
            <div className="composer-actions">
              <span><SlidersHorizontal aria-hidden="true" size={17} /> Live board analysis</span>
              <button type="submit" aria-label="Send message" disabled={isSending || !draft.trim()}>
                <Send aria-hidden="true" size={19} />
              </button>
            </div>
          </form>
          <p>Skylark Signal can make mistakes. Verify key decisions.</p>
        </div>
      </main>

      <div id="evidence" className="evidence-shell desktop-evidence">
        <SourcesPanel
          sources={activeTurn?.sources ?? []}
          caveats={activeTurn?.caveats ?? []}
          quality={activeTurn?.quality ?? null}
        />
      </div>
      {evidenceOpen ? <>
        <div
          id="mobile-evidence-dialog"
          ref={dialogRef}
          className="evidence-shell mobile-evidence open"
          role="dialog"
          aria-modal="true"
          aria-label="Evidence and data quality"
          tabIndex={-1}
          onKeyDown={handleDialogKeyDown}
        >
          <SourcesPanel
            sources={activeTurn?.sources ?? []}
            caveats={activeTurn?.caveats ?? []}
            quality={activeTurn?.quality ?? null}
            onClose={closeEvidence}
          />
        </div>
        <div className="drawer-backdrop" aria-hidden="true" tabIndex={-1} onPointerDown={closeEvidence} />
      </> : null}
    </div>
  );
}
