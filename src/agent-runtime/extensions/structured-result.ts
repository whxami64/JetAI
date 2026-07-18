import { defineTool, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { TSchema, Static } from "typebox";
import { Check, Errors } from "typebox/value";
import { RuntimeError } from "../errors.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import { trace } from "../tracing/trace.js";

export interface StructuredResultCapture<T> {
  readonly tool: ToolDefinition;
  get(): T | undefined;
  clear(): void;
}

export function createStructuredResultCapture<const Schema extends TSchema>(options: {
  name: string;
  label: string;
  description: string;
  schema: Schema;
  runtimeContext: RuntimeContext;
}): StructuredResultCapture<Static<Schema>> {
  let captured: Static<Schema> | undefined;
  const tool = defineTool({
    name: options.name,
    label: options.label,
    description: `${options.description} Call this tool alone as your final action.`,
    parameters: options.schema,
    executionMode: "sequential",
    async execute(_toolCallId, params) {
      if (captured !== undefined) {
        throw new RuntimeError("RESULT_ALREADY_SUBMITTED", "A final result was already submitted");
      }
      if (!Check(options.schema, params)) {
        const reason = Errors(options.schema, params)
          .slice(0, 3)
          .map((error) => error.message)
          .join("; ");
        await trace(options.runtimeContext, "result.invalid", { reason });
        throw new RuntimeError("RESULT_INVALID", `Invalid final result: ${reason}`);
      }
      captured = structuredClone(params);
      await trace(options.runtimeContext, "result.submitted");
      return {
        content: [{ type: "text", text: "Result accepted." }],
        details: {},
        terminate: true,
      };
    },
  });
  return {
    tool,
    get: () => {
      if (captured === undefined) return undefined;
      // TypeBox's generic Static type is represented as `any` to ESLint.
      // eslint-disable-next-line @typescript-eslint/no-unsafe-return
      return structuredClone(captured);
    },
    clear: () => {
      captured = undefined;
    },
  };
}
