import { Type } from "typebox";

export const UnknownRecordSchema = Type.Record(Type.String(), Type.Unknown());

export const ErrorDetailSchema = Type.Object(
  {
    code: Type.String({ minLength: 1 }),
    message: Type.String({ minLength: 1 }),
  },
  { additionalProperties: false },
);

export const RunStatusSchema = Type.Union([
  Type.Literal("completed"),
  Type.Literal("failed"),
  Type.Literal("aborted"),
  Type.Literal("timed_out"),
]);

export const RunMetricsSchema = Type.Object(
  {
    startedAt: Type.String({ minLength: 1 }),
    completedAt: Type.Optional(Type.String({ minLength: 1 })),
    durationMs: Type.Optional(Type.Number({ minimum: 0 })),
    turns: Type.Optional(Type.Integer({ minimum: 0 })),
    toolCalls: Type.Optional(Type.Integer({ minimum: 0 })),
    inputTokens: Type.Optional(Type.Integer({ minimum: 0 })),
    outputTokens: Type.Optional(Type.Integer({ minimum: 0 })),
    totalTokens: Type.Optional(Type.Integer({ minimum: 0 })),
    estimatedCost: Type.Optional(Type.Number({ minimum: 0 })),
  },
  { additionalProperties: false },
);
