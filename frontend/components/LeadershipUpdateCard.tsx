// Draft leadership update rendering is implemented in Task 4.
"use client";

import { useId, useState } from "react";
import { Check, Copy, Sparkles } from "lucide-react";
import type { LeadershipUpdate } from "@/lib/types";

type Props = { update: LeadershipUpdate };

export function LeadershipUpdateCard({ update }: Props) {
  const [copied, setCopied] = useState(false);
  const cardId = useId();
  const titleId = `${cardId}-leadership-title`;
  const currency = (value: string | number) => new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Number(value));

  async function copyMarkdown() {
    await navigator.clipboard.writeText(update.markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="leadership-card" aria-labelledby={titleId}>
      <div className="leadership-title-row">
        <Sparkles aria-hidden="true" size={19} />
        <h3 id={titleId}>Leadership update</h3>
      </div>
      <div className="leadership-metric">
        <span>Headline pipeline</span>
        <strong>{currency(update.headline_pipeline_value_inr)}</strong>
      </div>
      <div className="leadership-grid">
        <section aria-labelledby={`${cardId}-sectors`}>
          <h4 id={`${cardId}-sectors`}>Sector breakdown</h4>
          {update.sector_breakdown.length ? <ul>
            {update.sector_breakdown.map((sector) => (
              <li key={sector.sector}>
                <span>{sector.sector} · {sector.deal_count} deals</span>
                <strong>{currency(sector.pipeline_value_inr)}</strong>
              </li>
            ))}
          </ul> : <p className="empty-leadership-section">No sector breakdown is available.</p>}
        </section>
        <section aria-labelledby={`${cardId}-risks`}>
          <h4 id={`${cardId}-risks`}>Notable risks</h4>
          {update.notable_at_risk.length ? <ul>
            {update.notable_at_risk.map((risk, index) => (
              <li key={`${risk.record_type}:${risk.record_id ?? risk.name ?? index}`}>
                <span>{risk.name ?? risk.record_id ?? `Unnamed ${risk.record_type}`} · {risk.reason}</span>
              </li>
            ))}
          </ul> : <p className="empty-leadership-section">No notable risks were identified.</p>}
        </section>
      </div>
      <p className="leadership-quality"><strong>Data quality:</strong> {update.quality_footnote}</p>
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
