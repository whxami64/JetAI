import { randomUUID } from "node:crypto";
import type { AgentDefinition } from "../agents/types.js";
import type { AgentRegistry } from "../agents/registry.js";
import type { RuntimeLimits } from "../config/types.js";
import { RuntimeError, asRuntimeError } from "../errors.js";
import { childRuntimeContext, type RuntimeContext } from "../runtime/runtime-context.js";
import type { DelegationTask } from "../schemas/delegation.js";
import type { SubagentResult } from "../schemas/agent-result.js";
import { SubagentResultSchema } from "../schemas/agent-result.js";
import type { SubagentRunSummary } from "../schemas/run-result.js";
import { validateValue } from "../schemas/validate.js";
import { trace } from "../tracing/trace.js";
import type { SubagentRunner } from "./runner.js";
import { Scheduler } from "./scheduler.js";

export class DelegationService {
  readonly #registry: AgentRegistry;
  readonly #runner: SubagentRunner;
  readonly #scheduler: Scheduler;
  readonly #limits: RuntimeLimits;
  readonly #summaries: SubagentRunSummary[] = [];

  constructor(registry: AgentRegistry, runner: SubagentRunner, limits: RuntimeLimits) {
    this.#registry = registry;
    this.#runner = runner;
    this.#limits = limits;
    this.#scheduler = new Scheduler(limits.maxParallelSubagents);
  }

  listSummaries(): SubagentRunSummary[] {
    return structuredClone(this.#summaries);
  }

  async delegate(
    parentAgent: AgentDefinition,
    parentContext: RuntimeContext,
    task: DelegationTask,
  ): Promise<SubagentResult> {
    this.#assertDelegation(parentAgent, parentContext, 1);
    const agent = this.#registry.get(task.agentId);
    return this.#execute(parentContext, agent, task);
  }

  async delegateParallel(
    parentAgent: AgentDefinition,
    parentContext: RuntimeContext,
    tasks: DelegationTask[],
  ): Promise<SubagentResult[]> {
    if (tasks.length > this.#limits.maxDelegatedTasks) {
      throw new RuntimeError(
        "PARALLEL_LIMIT_EXCEEDED",
        `A parallel batch may contain at most ${this.#limits.maxDelegatedTasks} tasks`,
      );
    }
    this.#assertDelegation(parentAgent, parentContext, tasks.length);
    const entries = tasks.map((task) => ({ task, agent: this.#registry.get(task.agentId) }));
    return Promise.all(entries.map(({ task, agent }) => this.#execute(parentContext, agent, task)));
  }

  #assertDelegation(parentAgent: AgentDefinition, context: RuntimeContext, count: number): void {
    if (parentAgent.canDelegate !== true) {
      throw new RuntimeError("DELEGATION_NOT_ALLOWED", `Agent ${parentAgent.id} cannot delegate`);
    }
    if (context.depth >= this.#limits.maxDelegationDepth) {
      throw new RuntimeError("DELEGATION_DEPTH_EXCEEDED", "Maximum delegation depth reached");
    }
    if (!context.delegationBudget.reserve(count)) {
      throw new RuntimeError("DELEGATION_BUDGET_EXCEEDED", "Delegated task budget exhausted");
    }
  }

  async #execute(
    parentContext: RuntimeContext,
    agent: AgentDefinition,
    task: DelegationTask,
  ): Promise<SubagentResult> {
    const childContext = childRuntimeContext(parentContext, randomUUID(), agent.id, parentContext.signal);
    await trace(childContext, "subagent.queued", { objectiveLength: task.objective.length });
    try {
      const timeoutMs = agent.timeoutMs ?? this.#limits.subagentTimeoutMs;
      const result = await this.#scheduler.run<SubagentResult>(
        async (signal) => {
          const activeContext = { ...childContext, signal };
          await trace(activeContext, "subagent.started");
          return this.#runner.run({
            agent,
            objective: task.objective,
            ...(task.context === undefined ? {} : { context: task.context }),
            ...(task.expectedOutput === undefined ? {} : { expectedOutput: task.expectedOutput }),
            runtimeContext: activeContext,
          });
        },
        {
          ...(parentContext.signal === undefined ? {} : { signal: parentContext.signal }),
          timeoutMs,
        },
      );
      const validated = validateValue(SubagentResultSchema, result, "Subagent runner result");
      if (
        validated.runId !== childContext.runId ||
        validated.parentRunId !== parentContext.runId ||
        validated.agentId !== agent.id
      ) {
        throw new RuntimeError("RESULT_INVALID", "Subagent runner returned mismatched run metadata");
      }
      if (JSON.stringify(validated).length > this.#limits.maxResultChars) {
        throw new RuntimeError("RESULT_INVALID", "Subagent result exceeds the configured size limit");
      }
      const eventType = validated.status === "completed"
        ? "subagent.completed"
        : validated.status === "timed_out"
          ? "subagent.timed_out"
          : validated.status === "aborted"
            ? "subagent.aborted"
            : "subagent.failed";
      await trace(childContext, eventType, { status: validated.status });
      this.#summaries.push({
        runId: validated.runId,
        agentId: validated.agentId,
        status: validated.status,
        summary: validated.summary,
      });
      return validated;
    } catch (error) {
      const runtimeError = asRuntimeError(error);
      const status = runtimeError.code === "SUBAGENT_TIMEOUT"
        ? "timed_out"
        : runtimeError.code === "RUN_ABORTED"
          ? "aborted"
          : "failed";
      await trace(
        childContext,
        status === "timed_out"
          ? "subagent.timed_out"
          : status === "aborted"
            ? "subagent.aborted"
            : "subagent.failed",
        { code: runtimeError.code, message: runtimeError.message },
      );
      const now = new Date().toISOString();
      const result: SubagentResult = {
        runId: childContext.runId,
        parentRunId: parentContext.runId,
        agentId: agent.id,
        status,
        summary: "",
        findings: [],
        evidence: [],
        unresolvedQuestions: [],
        metrics: { startedAt: now, completedAt: now, durationMs: 0 },
        error: { code: runtimeError.code, message: runtimeError.message },
      };
      this.#summaries.push({
        runId: result.runId,
        agentId: result.agentId,
        status: result.status,
        summary: result.summary,
      });
      return result;
    }
  }
}
