import type { InlineExtension } from "@earendil-works/pi-coding-agent";
import { trace } from "../tracing/trace.js";
import type { RuntimeContext } from "../runtime/runtime-context.js";

export const CODING_TOOL_NAMES = new Set(["bash", "edit", "find", "grep", "ls", "read", "write"]);

export function getToolDenialReason(
  toolName: string,
  allowedTools: ReadonlySet<string>,
  canDelegate: boolean,
): string | undefined {
  const delegation = toolName === "delegate_to_subagent" || toolName === "delegate_parallel";
  if (!allowedTools.has(toolName) || CODING_TOOL_NAMES.has(toolName) || (delegation && !canDelegate)) {
    return `TOOL_NOT_ALLOWED: ${toolName}`;
  }
  return undefined;
}

export function assertExactToolAllowlist(active: string[], expected: ReadonlySet<string>): void {
  const unexpected = active.filter((name) => !expected.has(name));
  const missing = [...expected].filter((name) => !active.includes(name));
  if (unexpected.length > 0 || missing.length > 0) {
    throw new Error(
      `Tool allowlist mismatch (unexpected: ${unexpected.join(", ") || "none"}; missing: ${missing.join(", ") || "none"})`,
    );
  }
}

export function createToolPolicyExtension(
  allowedTools: ReadonlySet<string>,
  runtimeContext: RuntimeContext,
  canDelegate: boolean,
): InlineExtension {
  return {
    name: "runtime-tool-policy",
    factory(pi) {
      pi.on("tool_call", async (event) => {
        const denialReason = getToolDenialReason(event.toolName, allowedTools, canDelegate);
        if (denialReason !== undefined) {
          await trace(runtimeContext, "tool.denied", {
            toolName: event.toolName,
            reason: "TOOL_NOT_ALLOWED",
          });
          return {
            block: true,
            reason: `${denialReason} is not enabled for ${runtimeContext.agentId}`,
          };
        }
        await trace(runtimeContext, "tool.requested", { toolName: event.toolName });
      });
      pi.on("tool_result", async (event) => {
        await trace(runtimeContext, event.isError ? "tool.failed" : "tool.completed", {
          toolName: event.toolName,
          isError: event.isError,
        });
      });
    },
  };
}
