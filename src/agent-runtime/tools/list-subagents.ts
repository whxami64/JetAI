import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { AgentRegistry } from "../agents/registry.js";

export function createListSubagentsTool(registry: AgentRegistry) {
  return defineTool({
    name: "list_subagents",
    label: "List subagents",
    description: "List specialists currently registered for bounded delegation.",
    parameters: Type.Object({}, { additionalProperties: false }),
    execute() {
      const agents = registry.list().map(({ id, description, canDelegate = false }) => ({
        id,
        description,
        canDelegate,
      }));
      return Promise.resolve({
        content: [{ type: "text", text: JSON.stringify(agents) }],
        details: { agents },
      });
    },
  });
}
