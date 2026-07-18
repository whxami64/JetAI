import type { TSchema, Static } from "typebox";
import { Check, Errors } from "typebox/value";
import { RuntimeError } from "../errors.js";

export function validateValue<const Schema extends TSchema>(
  schema: Schema,
  value: unknown,
  label: string,
): Static<Schema> {
  // TypeBox's generic predicate is represented as `any` to ESLint, but this branch is checked.
  // eslint-disable-next-line @typescript-eslint/no-unsafe-return
  if (Check(schema, value)) return value;
  const details = Errors(schema, value)
    .slice(0, 3)
    .map((error) => `${error.instancePath || "/"}: ${error.message}`)
    .join("; ");
  throw new RuntimeError("RESULT_INVALID", `${label} is invalid: ${details}`);
}
