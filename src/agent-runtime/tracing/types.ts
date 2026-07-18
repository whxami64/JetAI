export const TRACE_EVENT_TYPES = [
  "run.created",
  "run.started",
  "run.completed",
  "run.failed",
  "run.aborted",
  "run.timed_out",
  "turn.started",
  "turn.completed",
  "tool.requested",
  "tool.completed",
  "tool.failed",
  "tool.denied",
  "subagent.queued",
  "subagent.started",
  "subagent.completed",
  "subagent.failed",
  "subagent.aborted",
  "subagent.timed_out",
  "result.submitted",
  "result.invalid",
] as const;

export type RuntimeTraceEventType = (typeof TRACE_EVENT_TYPES)[number];

export interface RuntimeTraceEvent {
  eventId: string;
  eventType: RuntimeTraceEventType;
  timestamp: string;
  rootRunId: string;
  runId: string;
  parentRunId?: string;
  agentId: string;
  depth: number;
  data: Record<string, unknown>;
}
