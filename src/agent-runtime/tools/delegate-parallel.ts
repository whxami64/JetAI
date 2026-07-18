import { defineTool } from "@earendil-works/pi-coding-agent";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import { ParallelDelegationSchema } from "../schemas/delegation.js";
import type { DelegationService } from "../subagents/delegation-service.js";

export function createDelegateParallelTool(
  service: DelegationService,
  parentAgent: AgentDefinition,
  runtimeContext: RuntimeContext,
) {
  return defineTool({
    name: "delegate_parallel",
    label: "Delegate in parallel",
    description: "Delegate independent tasks with bounded concurrency and ordered results.",
    parameters: ParallelDelegationSchema,
    async execute(_toolCallId, { tasks }) {
      const results = await service.delegateParallel(parentAgent, runtimeContext, tasks);
      return {
        content: [{ type: "text", text: JSON.stringify(results) }],
        details: { results },
      };
    },
  });
}
