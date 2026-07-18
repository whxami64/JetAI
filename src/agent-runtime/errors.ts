export const ERROR_CODES = [
  "CONFIG_INVALID",
  "MODEL_NOT_CONFIGURED",
  "MODEL_AUTH_MISSING",
  "AGENT_NOT_FOUND",
  "AGENT_REGISTRY_INVALID",
  "TOOL_NOT_ALLOWED",
  "DELEGATION_NOT_ALLOWED",
  "DELEGATION_DEPTH_EXCEEDED",
  "DELEGATION_BUDGET_EXCEEDED",
  "PARALLEL_LIMIT_EXCEEDED",
  "SUBAGENT_TIMEOUT",
  "RUN_ABORTED",
  "RESULT_NOT_SUBMITTED",
  "RESULT_INVALID",
  "RESULT_ALREADY_SUBMITTED",
  "MCP_DISABLED",
  "MCP_SERVER_NOT_FOUND",
  "MCP_CONNECTION_FAILED",
  "MCP_TOOL_SCHEMA_UNSUPPORTED",
  "TRACE_WRITE_FAILED",
] as const;

export type RuntimeErrorCode = (typeof ERROR_CODES)[number];

export class RuntimeError extends Error {
  readonly code: RuntimeErrorCode;

  constructor(code: RuntimeErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "RuntimeError";
    this.code = code;
  }
}

export function asRuntimeError(error: unknown): RuntimeError {
  if (error instanceof RuntimeError) return error;
  if (error instanceof Error) {
    return new RuntimeError("RESULT_INVALID", error.message, { cause: error });
  }
  return new RuntimeError("RESULT_INVALID", "Unknown runtime error");
}
