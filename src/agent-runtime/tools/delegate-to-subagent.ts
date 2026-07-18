import { defineTool } from "@earendil-works/pi-coding-agent";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import { DelegationTaskSchema } from "../schemas/delegation.js";
import type { DelegationService } from "../subagents/delegation-service.js";

export function createDelegateToSubagentTool(
  service: DelegationService,
  parentAgent: AgentDefinition,
  runtimeContext: RuntimeContext,
) {
  return defineTool({
    name: "delegate_to_subagent",
    label: "Delegate to subagent",
    description: "Delegate one bounded objective and explicit context to an isolated specialist.",
    parameters: DelegationTaskSchema,
    async execute(_toolCallId, task) {
      const result = await service.delegate(parentAgent, runtimeContext, task);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: { result },
      };
    },
  });
}
