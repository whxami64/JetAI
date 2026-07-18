import type { AgentDefinition } from "../agents/types.js";
import { DEFAULT_LIMITS, type RuntimeConfig } from "../config/types.js";
import { DelegationBudget, type RuntimeContext } from "../runtime/runtime-context.js";
import type { SubagentResult } from "../schemas/agent-result.js";
import type { SubagentRunRequest } from "../subagents/runner.js";
import { MemoryEventStore } from "../tracing/event-store.js";

export const specialist: AgentDefinition = {
  id: "specialist",
  description: "Test specialist",
  systemPrompt: "Use only supplied test context.",
  allowedTools: [],
  canDelegate: false,
};

export const delegator: AgentDefinition = {
  id: "delegator",
  description: "Test delegator",
  systemPrompt: "Delegate bounded test tasks.",
  allowedTools: ["list_subagents", "delegate_to_subagent", "delegate_parallel"],
  canDelegate: true,
};

export function testConfig(overrides: Partial<RuntimeConfig["limits"]> = {}): RuntimeConfig {
  return {
    cwd: process.cwd(),
    model: { thinkingLevel: "off" },
    limits: { ...DEFAULT_LIMITS, ...overrides },
    sessionDir: ".runtime/sessions",
    traceDir: ".runtime/traces",
    mcp: { enabled: false, configPath: ".config/mcp.json" },
  };
}

export function testContext(options: {
  agent?: AgentDefinition;
  depth?: number;
  maximum?: number;
  signal?: AbortSignal;
} = {}): RuntimeContext {
  const agent = options.agent ?? delegator;
  return {
    runId: "parent-run",
    rootRunId: "root-run",
    agentId: agent.id,
    depth: options.depth ?? 0,
    delegationBudget: new DelegationBudget(options.maximum ?? 8),
    eventStore: new MemoryEventStore(),
    ...(options.signal === undefined ? {} : { signal: options.signal }),
  };
}

export function fakeResult(request: SubagentRunRequest, summary = "ok"): SubagentResult {
  const now = new Date().toISOString();
  return {
    runId: request.runtimeContext.runId,
    parentRunId: request.runtimeContext.parentRunId ?? request.runtimeContext.rootRunId,
    agentId: request.agent.id,
    status: "completed",
    summary,
    findings: [],
    evidence: [],
    unresolvedQuestions: [],
    metrics: { startedAt: now, completedAt: now, durationMs: 0 },
  };
}
