import { Type, type Static } from "typebox";
import { AgentFindingSchema } from "./agent-result.js";
import { ErrorDetailSchema, RunMetricsSchema, RunStatusSchema } from "./common.js";

export const SubagentRunSummarySchema = Type.Object(
  {
    runId: Type.String({ minLength: 1 }),
    agentId: Type.String({ minLength: 1 }),
    status: RunStatusSchema,
    summary: Type.String(),
  },
  { additionalProperties: false },
);

export const SupervisorSubmissionSchema = Type.Object(
  {
    summary: Type.String(),
    findings: Type.Array(AgentFindingSchema),
    unresolvedQuestions: Type.Array(Type.String()),
  },
  { additionalProperties: false },
);

export const AgentRunResultSchema = Type.Object(
  {
    runId: Type.String({ minLength: 1 }),
    status: RunStatusSchema,
    summary: Type.String(),
    findings: Type.Array(AgentFindingSchema),
    unresolvedQuestions: Type.Array(Type.String()),
    subagentRuns: Type.Array(SubagentRunSummarySchema),
    metrics: RunMetricsSchema,
    error: Type.Optional(ErrorDetailSchema),
  },
  { additionalProperties: false },
);

export type SubagentRunSummary = Static<typeof SubagentRunSummarySchema>;
export type SupervisorSubmission = Static<typeof SupervisorSubmissionSchema>;
export type AgentRunResult = Static<typeof AgentRunResultSchema>;
