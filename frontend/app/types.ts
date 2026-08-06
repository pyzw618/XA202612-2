export type ToolCall = {
  call_id: string;
  tool_name: string;
  arguments: unknown;
  result: unknown;
  status: "success" | "error" | "timeout" | "cancelled" | "partial" | string;
  sequence: number;
  error?: string;
  latency_ms?: number;
};

export type MemoryEvent = {
  event_id: string;
  source_type: string;
  event_type: string;
  user_id: string;
  session_id: string;
  turn_id: string;
  scene?: string;
  task_type?: string;
  occurred_at: string;
  text?: string;
  payload?: Record<string, unknown>;
  tool_calls?: ToolCall[];
  schema_version?: string;
  source_hash?: string;
  redactions?: string[];
  quality?: Record<string, unknown>;
};

export type MemoryCardData = {
  memory_id: string;
  memory_type: "preference" | "knowledge" | "fact" | string;
  title: string;
  summary: string;
  relevance?: number;
  source?: string;
  level?: string;
  scope?: string;
  updated_at?: string;
  tags?: string[];
  used?: boolean;
  knowledge_type?: "workflow" | "template" | string;
};

export type FactProposal = {
  proposal_id: string;
  subject: string;
  predicate: string;
  object: string;
  evidence: string;
  confidence: number;
  admission_reason: string;
  suggested_scope?: "global" | "project" | null;
  status?: string;
};

export type ReplayTurn = {
  turn_id: string;
  user_message: string;
  retrieval_query?: string;
  assistant_message: string;
  occurred_at?: string;
  tool_calls: ToolCall[];
  candidate_memories: MemoryCardData[];
  used_memory_ids: string[];
  fact_proposals: FactProposal[];
  write_summary?: string[];
  latency_ms?: number;
  events?: MemoryEvent[];
};

export type ReplaySession = {
  schema_version: "conversation-replay/1.0";
  session_id: string;
  title: string;
  source: "sample" | "json" | "live";
  read_only: boolean;
  turns: ReplayTurn[];
  events: MemoryEvent[];
};

export type ViewId =
  | "chat"
  | "ingestion"
  | "retrieval"
  | "preferences"
  | "facts"
  | "knowledge"
  | "conflicts"
  | "forget"
  | "safety"
  | "evaluation"
  | "settings";
