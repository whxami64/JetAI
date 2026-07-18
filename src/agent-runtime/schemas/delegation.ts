import { Type, type Static } from "typebox";
import { UnknownRecordSchema } from "./common.js";

export const DelegationTaskSchema = Type.Object(
  {
    agentId: Type.String({ minLength: 1 }),
    objective: Type.String({ minLength: 1 }),
    context: Type.Optional(UnknownRecordSchema),
    expectedOutput: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);

export const ParallelDelegationSchema = Type.Object(
  { tasks: Type.Array(DelegationTaskSchema, { minItems: 1 }) },
  { additionalProperties: false },
);

export type DelegationTask = Static<typeof DelegationTaskSchema>;
