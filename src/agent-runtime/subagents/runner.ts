import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import type { SubagentResult } from "../schemas/agent-result.js";

export interface SubagentRunRequest {
  agent: AgentDefinition;
  objective: string;
  context?: Record<string, unknown>;
  expectedOutput?: string;
  runtimeContext: RuntimeContext;
}

export interface SubagentRunner {
  /** Implementations must honor `request.runtimeContext.signal` and settle after it aborts. */
  run(request: SubagentRunRequest): Promise<SubagentResult>;
  close(): Promise<void>;
}
