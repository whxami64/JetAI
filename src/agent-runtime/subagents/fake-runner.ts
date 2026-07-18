import type { SubagentResult } from "../schemas/agent-result.js";
import type { SubagentRunRequest, SubagentRunner } from "./runner.js";

export type FakeRunBehavior = (request: SubagentRunRequest) => Promise<SubagentResult>;

export class FakeSubagentRunner implements SubagentRunner {
  readonly requests: SubagentRunRequest[] = [];
  closed = false;
  readonly #behavior: FakeRunBehavior;

  constructor(behavior: FakeRunBehavior = successfulFakeResult) {
    this.#behavior = behavior;
  }

  async run(request: SubagentRunRequest): Promise<SubagentResult> {
    this.requests.push(request);
    return this.#behavior(request);
  }

  close(): Promise<void> {
    this.closed = true;
    return Promise.resolve();
  }
}

export function successfulFakeResult(request: SubagentRunRequest): Promise<SubagentResult> {
  const now = new Date().toISOString();
  return Promise.resolve({
    runId: request.runtimeContext.runId,
    parentRunId: request.runtimeContext.parentRunId ?? request.runtimeContext.rootRunId,
    agentId: request.agent.id,
    status: "completed",
    summary: `Completed: ${request.objective}`,
    findings: [],
    evidence: [],
    unresolvedQuestions: [],
    metrics: { startedAt: now, completedAt: now, durationMs: 0 },
  });
}
