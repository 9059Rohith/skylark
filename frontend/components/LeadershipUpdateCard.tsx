// Draft leadership update rendering is implemented in Task 4.
"use client";

import { useState } from "react";
import { Check, Copy, Sparkles } from "lucide-react";
import type { LeadershipUpdate } from "@/lib/types";

type Props = { update: LeadershipUpdate };

export function LeadershipUpdateCard({ update }: Props) {
  const [copied, setCopied] = useState(false);

  async function copyMarkdown() {
    await navigator.clipboard.writeText(update.markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="leadership-card" aria-labelledby="leadership-title">
      <div className="leadership-title-row">
        <Sparkles aria-hidden="true" size={19} />
        <h3 id="leadership-title">Leadership update</h3>
      </div>
      <p className="leadership-headline">
        Pipeline stands at {new Intl.NumberFormat("en-IN", {
          style: "currency",
          currency: "INR",
          maximumFractionDigits: 0,
        }).format(Number(update.headline_pipeline_value_inr))}.
      </p>
      {update.notable_at_risk[0] ? (
        <p>{update.notable_at_risk[0].name ?? "An item"}: {update.notable_at_risk[0].reason}.</p>
      ) : null}
      <div className="leadership-footer">
        <span><i aria-hidden="true" /> Draft · Not sent</span>
        <button type="button" className="outline-button" onClick={copyMarkdown}>
          {copied ? <Check aria-hidden="true" size={16} /> : <Copy aria-hidden="true" size={16} />}
          {copied ? "Copied" : "Copy as Markdown"}
        </button>
        <span className="sr-only" role="status" aria-live="polite">
          {copied ? "Copied to clipboard" : ""}
        </span>
      </div>
    </section>
  );
}
