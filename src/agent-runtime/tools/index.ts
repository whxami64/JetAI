import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { AgentRegistry } from "../agents/registry.js";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import type { DelegationService } from "../subagents/delegation-service.js";
import { createDelegateParallelTool } from "./delegate-parallel.js";
import { createDelegateToSubagentTool } from "./delegate-to-subagent.js";
import { createListSubagentsTool } from "./list-subagents.js";

export const DELEGATION_TOOL_NAMES = [
  "list_subagents",
  "delegate_to_subagent",
  "delegate_parallel",
] as const;

export function createDelegationTools(
  registry: AgentRegistry,
  service: DelegationService,
  parentAgent: AgentDefinition,
  runtimeContext: RuntimeContext,
): ToolDefinition[] {
  return [
    createListSubagentsTool(registry),
    createDelegateToSubagentTool(service, parentAgent, runtimeContext),
    createDelegateParallelTool(service, parentAgent, runtimeContext),
  ];
}

export * from "./delegate-parallel.js";
export * from "./delegate-to-subagent.js";
export * from "./list-subagents.js";
