export type Source = {
  board_id: string;
  board_name: string;
  item_count: number;
  partial: boolean;
  error: string | null;
};

export type DataQualityReport = {
  total_rows: number;
  included_rows: number;
  exclusions: Record<string, number>;
  normalization_notes: string[];
  duplicate_records: [string, string][];
};

export type LeadershipQuality = {
  pipeline: DataQualityReport;
  sector: DataQualityReport;
  gaps: DataQualityReport;
  operational_risks: DataQualityReport;
};

export type LeadershipUpdate = {
  headline_pipeline_value_inr: string | number;
  sector_breakdown: Array<{
    sector: string;
    deal_count: number;
    pipeline_value_inr: string | number;
  }>;
  notable_at_risk: Array<{
    record_type: string;
    record_id: string | null;
    name: string | null;
    reason: string;
  }>;
  quality: LeadershipQuality;
  quality_footnote: string;
  markdown: string;
};

export type ChatEvent =
  | { event: "status"; stage: string; message: string }
  | { event: "sources"; sources: Source[] }
  | { event: "caveats"; caveats: string[]; quality: DataQualityReport | null }
  | { event: "leadership_update"; leadership_update: LeadershipUpdate }
  | { event: "token"; token: string }
  | { event: "done"; session_id: string; intent: string }
  | { event: "error"; code: string; message: string };

export type TurnStatus = "idle" | "streaming" | "complete" | "error";

export type ChatTurn = {
  id: string;
  prompt: string;
  answer: string;
  stage: string | null;
  statusMessage: string | null;
  status: TurnStatus;
  sources: Source[];
  caveats: string[];
  quality: DataQualityReport | null;
  leadershipUpdate: LeadershipUpdate | null;
  intent: string | null;
  error: { code: string; message: string } | null;
};
