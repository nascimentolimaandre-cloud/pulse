/**
 * Flow Health — types mirror the FastAPI pulse-data contract for
 * GET /data/v1/metrics/flow-health (FDD-KB-003 + FDD-KB-004 + squad-view expansion).
 *
 * Anti-surveillance contract: this payload MUST NOT contain `assignee`,
 * `author`, reporter, or any PII. If it ever appears, treat as bug.
 */

export type BaselineSource =
  | 'squad_p85_90d'
  | 'tenant_p85_90d'
  | 'tenant_p85_90d_fallback'
  | 'absolute_fallback';

export type StatusCategory = 'in_progress' | 'in_review';

/** Issue type taxonomy coming from Jira (normalised to lowercase by backend). */
export type IssueType = 'epic' | 'story' | 'task' | 'bug' | 'subtask' | string;

export interface AgingWipItem {
  issue_key: string;
  /** Real issue title, when available. Fallback to issue_key on render. */
  title: string | null;
  /** Truncated (~300 chars with ellipsis) short description — may be null. */
  description: string | null;
  /** Issue type (epic/story/task/bug/subtask or other string). */
  issue_type: IssueType | null;
  age_days: number;
  /** Raw Jira status (PT-BR, e.g., "Em Andamento"). */
  status: string;
  status_category: StatusCategory;
  squad_key: string | null;
  /** Friendly squad name (from jira_project_catalog). Fallback = squad_key. */
  squad_name: string | null;
  is_at_risk: boolean;
}

export interface AgingWipSummary {
  count: number;
  p50_days: number | null;
  p85_days: number | null;
  at_risk_count: number;
  at_risk_threshold_days: number | null;
  baseline_source: BaselineSource;
}

export interface FlowEfficiencyData {
  /** 0..1 — render as percentage. Null when `insufficient_data`. */
  value: number | null;
  sample_size: number;
  formula_version: 'v1_simplified';
  /** PT-BR text — render inline, NEVER tooltip-only. */
  formula_disclaimer: string;
  insufficient_data: boolean;
}

/** Per-squad aggregated Flow Health summary. Ordered by at_risk_count DESC from backend. */
export interface SquadFlowSummary {
  squad_key: string;
  squad_name: string;
  wip_count: number;
  at_risk_count: number;
  /** 0..1 */
  risk_pct: number;
  p50_age_days: number | null;
  p85_age_days: number | null;
  /** 0..1, per-squad. Null when insufficient data. */
  flow_efficiency: number | null;
  fe_sample_size: number;
  /** Throughput — items concluded in the last 30d (intensity of delivery). */
  intensity_throughput_30d: number;
}

export interface FlowHealthResponse {
  period: string;
  period_start: string | null;
  period_end: string;
  team_id: string | null;
  calculated_at: string;
  squad_key: string | null;
  period_days: number;
  aging_wip: AgingWipSummary;
  /** Up to 500 items (backend cap). */
  aging_wip_items: AgingWipItem[];
  flow_efficiency: FlowEfficiencyData;
  /** All squads with active flow in the period. Always present; single-item when squad_key filter is set. */
  squads: SquadFlowSummary[];
}

/** UI-only — kept for backward compat with older consumers. Unused by new view. */
export type AgingWipGrouping = 'item' | 'squad';

/** Legacy client-side aggregation row. Kept for backward compat. */
export interface AgingWipSquadRow {
  squad_key: string;
  wip_count: number;
  at_risk_count: number;
  at_risk_pct: number;
  max_age_days: number;
}

/** Sort options for the squad list. */
export type SquadSortKey =
  | 'at_risk'
  | 'risk_pct'
  | 'flow_efficiency'
  | 'wip'
  | 'intensity'
  | 'name';
