import { Type, type Static } from "typebox";
import { ErrorDetailSchema, RunMetricsSchema, RunStatusSchema, UnknownRecordSchema } from "./common.js";

export const AgentFindingSchema = Type.Object(
  {
    id: Type.String({ minLength: 1 }),
    title: Type.String({ minLength: 1 }),
    description: Type.String({ minLength: 1 }),
    severity: Type.Optional(
      Type.Union([
        Type.Literal("info"),
        Type.Literal("low"),
        Type.Literal("medium"),
        Type.Literal("high"),
        Type.Literal("critical"),
      ]),
    ),
    confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
    evidenceIds: Type.Array(Type.String()),
    metadata: Type.Optional(UnknownRecordSchema),
  },
  { additionalProperties: false },
);

export const EvidenceReferenceSchema = Type.Object(
  {
    id: Type.String({ minLength: 1 }),
    sourceType: Type.String({ minLength: 1 }),
    sourceId: Type.String({ minLength: 1 }),
    locator: Type.Optional(Type.String()),
    description: Type.Optional(Type.String()),
    metadata: Type.Optional(UnknownRecordSchema),
  },
  { additionalProperties: false },
);

export const SubagentSubmissionSchema = Type.Object(
  {
    summary: Type.String(),
    findings: Type.Array(AgentFindingSchema),
    evidence: Type.Array(EvidenceReferenceSchema),
    unresolvedQuestions: Type.Array(Type.String()),
    confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  },
  { additionalProperties: false },
);

export const SubagentResultSchema = Type.Object(
  {
    runId: Type.String({ minLength: 1 }),
    parentRunId: Type.String({ minLength: 1 }),
    agentId: Type.String({ minLength: 1 }),
    status: RunStatusSchema,
    summary: Type.String(),
    findings: Type.Array(AgentFindingSchema),
    evidence: Type.Array(EvidenceReferenceSchema),
    unresolvedQuestions: Type.Array(Type.String()),
    confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
    metrics: RunMetricsSchema,
    error: Type.Optional(ErrorDetailSchema),
  },
  { additionalProperties: false },
);

export type AgentFinding = Static<typeof AgentFindingSchema>;
export type EvidenceReference = Static<typeof EvidenceReferenceSchema>;
export type SubagentSubmission = Static<typeof SubagentSubmissionSchema>;
export type SubagentResult = Static<typeof SubagentResultSchema>;
