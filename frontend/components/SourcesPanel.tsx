// Source lineage and caveat rendering is implemented in Task 4.
"use client";

import { useId, useState } from "react";
import { AlertTriangle, Check, Database, ShieldCheck } from "lucide-react";
import type { DataQualityReport, Source } from "@/lib/types";

type Props = {
  sources: Source[];
  caveats: string[];
  quality: DataQualityReport | null;
  onClose?: () => void;
};

const humanize = (value: string) => value.split(":").at(-1)?.replaceAll("_", " ") ?? value;

export function SourcesPanel({ sources, caveats, quality, onClose }: Props) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const panelId = useId();
  const sourcesId = `${panelId}-sources`;
  const qualityId = `${panelId}-quality`;
  return (
    <aside className="evidence-rail" aria-label="Evidence and data quality">
      {onClose ? (
        <button type="button" className="mobile-close" data-dialog-close onClick={onClose} aria-label="Close evidence panel">×</button>
      ) : null}
      <section className="evidence-section" aria-labelledby={sourcesId}>
        <div className="rail-heading">
          <Database aria-hidden="true" size={19} />
          <h2 id={sourcesId}>Sources queried</h2>
        </div>
        {sources.length ? (
          <div className="source-timeline">
            {sources.map((source) => (
              <article className="source-row" key={source.board_id}>
                <span className={source.partial ? "source-status warning" : "source-status"} aria-hidden="true">
                  {source.partial ? "!" : <Check size={12} />}
                </span>
                <div>
                  <div className="source-name-row">
                    <h3>{source.board_name}</h3>
                    <span className={source.partial ? "live-tag partial" : "live-tag"}>
                      <i aria-hidden="true" /> {source.partial ? "Partial" : "Live"}
                    </span>
                  </div>
                  <p>monday.com</p>
                  <dl>
                    <div><dt>Board ID</dt><dd>{source.board_id}</dd></div>
                    <div><dt>Items scanned</dt><dd>{source.item_count}</dd></div>
                  </dl>
                  {source.error ? <p className="source-error">{source.error}</p> : null}
                </div>
              </article>
            ))}
          </div>
        ) : <p className="empty-rail">Ask a question to see the live evidence used this turn.</p>}
      </section>

      <section className="evidence-section quality-section" aria-labelledby={qualityId}>
        <div className="rail-heading">
          <ShieldCheck aria-hidden="true" size={20} />
          <h2 id={qualityId}>Data quality</h2>
        </div>
        {caveats.map((caveat) => (
          <div className="quality-alert" key={caveat}>
            <AlertTriangle aria-hidden="true" size={18} />
            <p>{caveat}</p>
          </div>
        ))}
        {quality ? (
          <>
            <div className="quality-summary">
              <span>Rows used</span>
              <strong>{quality.included_rows} / {quality.total_rows}</strong>
            </div>
            <div className={detailsOpen ? "quality-details open" : "quality-details"}>
              <button type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((open) => !open)}>
                <span>Quality details</span><span aria-hidden="true">+</span>
              </button>
              {detailsOpen ? <div className="detail-stack">
                {Object.entries(quality.exclusions).map(([reason, count]) => (
                  <p key={reason}><strong>{count} excluded:</strong> {humanize(reason)}</p>
                ))}
                {quality.normalization_notes.map((note) => <p key={note}>{note}</p>)}
                {quality.duplicate_records.map(([first, second]) => (
                  <p key={`${first}:${second}`}>Possible duplicate: {first} ↔ {second}</p>
                ))}
                {!Object.keys(quality.exclusions).length && !quality.normalization_notes.length && !quality.duplicate_records.length ? (
                  <p>No material quality exceptions were reported.</p>
                ) : null}
              </div> : null}
            </div>
          </>
        ) : caveats.length ? null : <p className="empty-rail">Quality accounting appears with every completed analysis.</p>}
      </section>
    </aside>
  );
}
