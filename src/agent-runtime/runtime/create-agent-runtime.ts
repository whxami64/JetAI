import { randomUUID } from "node:crypto";
import { join } from "node:path";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import { AgentRegistry } from "../agents/registry.js";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeConfig } from "../config/types.js";
import { loadRuntimeConfig } from "../config/env.js";
import { RuntimeError, asRuntimeError } from "../errors.js";
import {
  CODING_TOOL_NAMES,
  createLifecycleTracingExtension,
  createStructuredResultCapture,
  createToolPolicyExtension,
} from "../extensions/index.js";
import { McpClientManager } from "../mcp/client-manager.js";
import type { McpConnectionFactory } from "../mcp/types.js";
import { AgentRunResultSchema, SupervisorSubmissionSchema, type AgentRunResult } from "../schemas/run-result.js";
import { validateValue } from "../schemas/validate.js";
import { DelegationService } from "../subagents/delegation-service.js";
import { EmbeddedSubagentRunner } from "../subagents/embedded-runner.js";
import type { SubagentRunner } from "../subagents/runner.js";
import { createDelegationTools, DELEGATION_TOOL_NAMES } from "../tools/index.js";
import type { EventStore } from "../tracing/event-store.js";
import { JsonlEventStore } from "../tracing/jsonl-event-store.js";
import { trace } from "../tracing/trace.js";
import { DelegationBudget, type RuntimeContext } from "./runtime-context.js";
import { PiSessionFactory, type RuntimeSession, type SessionFactory } from "./create-pi-session.js";

export interface AgentRunInput {
  objective: string;
  context?: Record<string, unknown>;
  runId?: string;
  signal?: AbortSignal;
}

export interface CreateAgentRuntimeOptions {
  config?: RuntimeConfig;
  agents?: AgentDefinition[];
  applicationTools?: ToolDefinition[];
  sessionFactory?: SessionFactory;
  subagentRunner?: SubagentRunner;
  mcpConnectionFactory?: McpConnectionFactory;
  eventStoreFactory?: (rootRunId: string) => EventStore;
  persistentSupervisor?: boolean;
}

export interface AgentRuntime {
  run(input: AgentRunInput): Promise<AgentRunResult>;
  tracePath(rootRunId: string): string;
  close(): Promise<void>;
}

const SUPERVISOR_PROMPT = `You are the product supervisor for a controlled, domain-neutral agent runtime.
Understand the objective and decide whether delegation is useful. Choose the smallest suitable specialist set.
Delegate only bounded tasks with necessary explicit context. Never fabricate a specialist result.
Reconcile conflicts and preserve unresolved disagreements. Do not make audit-specific claims.
Submit exactly one final result through submit_supervisor_result as your final action.`;

function assertSafeCustomTools(tools: ToolDefinition[]): void {
  const names = new Set<string>();
  for (const tool of tools) {
    if (CODING_TOOL_NAMES.has(tool.name)) {
      throw new RuntimeError("TOOL_NOT_ALLOWED", `Product runtime cannot register coding tool ${tool.name}`);
    }
    if (names.has(tool.name)) {
      throw new RuntimeError("CONFIG_INVALID", `Duplicate custom tool: ${tool.name}`);
    }
    names.add(tool.name);
  }
}

function emptyMetrics(startedAt: string) {
  const completedAt = new Date().toISOString();
  return {
    startedAt,
    completedAt,
    durationMs: Date.parse(completedAt) - Date.parse(startedAt),
  };
}

function assertSafeRunId(runId: string): void {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(runId)) {
    throw new RuntimeError(
      "CONFIG_INVALID",
      "runId must contain only letters, numbers, underscores, or hyphens",
    );
  }
}

async function settleCleanup(tasks: Promise<unknown>[]): Promise<void> {
  const results = await Promise.allSettled(tasks);
  for (const result of results) {
    if (result.status === "rejected") {
      const message = result.reason instanceof Error ? result.reason.message : "Runtime cleanup failed";
      process.emitWarning(message, { code: "RUNTIME_CLEANUP_FAILED" });
    }
  }
}

function validateRuntimeConfig(config: RuntimeConfig): void {
  const { limits } = config;
  if (
    limits.maxParallelSubagents < 1 ||
    limits.subagentTimeoutMs < 1 ||
    limits.maxResultChars < 1 ||
    limits.maxDelegationDepth < 0 ||
    limits.maxDelegatedTasks < 0 ||
    limits.maxRetries < 0
  ) {
    throw new RuntimeError("CONFIG_INVALID", "Runtime limits contain an invalid value");
  }
}

export async function createAgentRuntime(
  options: CreateAgentRuntimeOptions = {},
): Promise<AgentRuntime> {
  const config = options.config ?? loadRuntimeConfig();
  validateRuntimeConfig(config);
  const applicationTools = options.applicationTools ?? [];
  assertSafeCustomTools(applicationTools);
  const mcp = new McpClientManager(config.mcp, options.mcpConnectionFactory);
  let sharedTools: ToolDefinition[];
  let registry: AgentRegistry;
  try {
    const mcpTools = await mcp.loadTools();
    assertSafeCustomTools([...applicationTools, ...mcpTools]);
    sharedTools = [...applicationTools, ...mcpTools];
    const knownTools = new Set([
      ...DELEGATION_TOOL_NAMES,
      ...sharedTools.map((tool) => tool.name),
    ]);
    registry = new AgentRegistry(options.agents ?? [], {
      knownTools,
      delegationEnabled: config.limits.maxDelegationDepth > 0,
    });
  } catch (error) {
    await mcp.close().catch(() => undefined);
    throw error;
  }
  const sessions = options.sessionFactory ?? new PiSessionFactory(config);
  const storeFactory = options.eventStoreFactory ?? ((runId: string) => new JsonlEventStore(join(config.traceDir, `${runId}.jsonl`)));
  let closed = false;
  const ownedRunners = new Set<SubagentRunner>();
  if (options.subagentRunner !== undefined) ownedRunners.add(options.subagentRunner);
  const activeControllers = new Set<AbortController>();
  const activeRuns = new Set<Promise<void>>();

  return {
    async run(input) {
      if (closed) throw new RuntimeError("CONFIG_INVALID", "Agent runtime is closed");
      if (input.objective.trim() === "") {
        throw new RuntimeError("CONFIG_INVALID", "Agent objective must not be empty");
      }
      const startedAt = new Date().toISOString();
      const runId = input.runId ?? randomUUID();
      assertSafeRunId(runId);
      const eventStore = storeFactory(runId);
      const shutdownController = new AbortController();
      const signal = input.signal === undefined
        ? shutdownController.signal
        : AbortSignal.any([input.signal, shutdownController.signal]);
      activeControllers.add(shutdownController);
      let completeRun = (): void => undefined;
      const runCompletion = new Promise<void>((resolve) => {
        completeRun = resolve;
      });
      activeRuns.add(runCompletion);
      const runtimeContext: RuntimeContext = {
        runId,
        rootRunId: runId,
        agentId: "supervisor",
        depth: 0,
        delegationBudget: new DelegationBudget(config.limits.maxDelegatedTasks),
        eventStore,
        signal,
      };
      const supervisor: AgentDefinition = {
        id: "supervisor",
        description: "Coordinates bounded specialist work and returns a validated result.",
        systemPrompt: SUPERVISOR_PROMPT,
        allowedTools: [
          ...DELEGATION_TOOL_NAMES,
          ...sharedTools.map((tool) => tool.name),
          "submit_supervisor_result",
        ],
        canDelegate: true,
      };
      const delegationRef: { current?: DelegationService } = {};
      const runner: SubagentRunner = options.subagentRunner ?? new EmbeddedSubagentRunner(
        sessions,
        config,
        (request) => {
          const activeDelegation = delegationRef.current;
          if (activeDelegation === undefined) {
            throw new RuntimeError("CONFIG_INVALID", "Delegation service is not initialized");
          }
          return {
            tools: [
              ...sharedTools,
              ...(request.agent.canDelegate === true
                ? createDelegationTools(
                    registry,
                    activeDelegation,
                    request.agent,
                    request.runtimeContext,
                  )
                : []),
            ],
          };
        },
      );
      const ownsRunner = options.subagentRunner === undefined;
      const delegation = new DelegationService(registry, runner, config.limits);
      delegationRef.current = delegation;
      const submission = createStructuredResultCapture({
        name: "submit_supervisor_result",
        label: "Submit supervisor result",
        description: "Submit the final validated supervisor result",
        schema: SupervisorSubmissionSchema,
        runtimeContext,
      });
      const delegationTools = createDelegationTools(registry, delegation, supervisor, runtimeContext);
      const allowed = new Set(supervisor.allowedTools);
      let session: RuntimeSession | undefined;
      try {
        await trace(runtimeContext, "run.created", { objectiveLength: input.objective.length });
        session = await sessions.create({
          agent: supervisor,
          runtimeContext,
          tools: [...sharedTools, ...delegationTools, submission.tool],
          extensions: [
            createLifecycleTracingExtension(runtimeContext),
            createToolPolicyExtension(allowed, runtimeContext, true),
          ],
          persistent: options.persistentSupervisor ?? false,
        });
        await trace(runtimeContext, "run.started");
        const prompt = [
          `Run ID: ${runId}`,
          `Objective: ${input.objective}`,
          `Explicit context: ${JSON.stringify(input.context ?? {})}`,
          `Available specialists: ${JSON.stringify(registry.list().map(({ id, description }) => ({ id, description })))}`,
          `Submit through submit_supervisor_result. Schema: ${JSON.stringify(SupervisorSubmissionSchema)}`,
        ].join("\n\n");
        await session.run(prompt, signal);
        for (let attempt = 0; submission.get() === undefined && attempt < config.limits.maxRetries; attempt += 1) {
          await session.run(
            "No valid result was submitted. Repair the output and call submit_supervisor_result exactly once.",
            signal,
          );
        }
        const payload = submission.get();
        if (payload === undefined) {
          throw new RuntimeError("RESULT_NOT_SUBMITTED", "Supervisor did not submit a valid result");
        }
        if (JSON.stringify(payload).length > config.limits.maxResultChars) {
          throw new RuntimeError("RESULT_INVALID", "Supervisor result exceeds the configured size limit");
        }
        const stats = session.stats();
        const completedAt = new Date().toISOString();
        const result: AgentRunResult = {
          runId,
          status: "completed",
          ...payload,
          subagentRuns: delegation.listSummaries(),
          metrics: {
            startedAt,
            completedAt,
            durationMs: Date.parse(completedAt) - Date.parse(startedAt),
            ...stats,
          },
        };
        validateValue(AgentRunResultSchema, result, "Supervisor result");
        await trace(runtimeContext, "run.completed", { status: result.status });
        return result;
      } catch (error) {
        const runtimeError = signal.aborted
          ? new RuntimeError("RUN_ABORTED", "Run was aborted", { cause: signal.reason })
          : asRuntimeError(error);
        const status = runtimeError.code === "RUN_ABORTED" ? "aborted" : "failed";
        await trace(runtimeContext, status === "aborted" ? "run.aborted" : "run.failed", {
          code: runtimeError.code,
          message: runtimeError.message,
        });
        return {
          runId,
          status,
          summary: "",
          findings: [],
          unresolvedQuestions: [],
          subagentRuns: delegation.listSummaries(),
          metrics: emptyMetrics(startedAt),
          error: { code: runtimeError.code, message: runtimeError.message },
        };
      } finally {
        await settleCleanup([
          ...(session === undefined ? [] : [session.close()]),
          eventStore.close(),
          ...(ownsRunner ? [runner.close()] : []),
        ]);
        activeControllers.delete(shutdownController);
        activeRuns.delete(runCompletion);
        completeRun();
      }
    },
    tracePath(rootRunId) {
      assertSafeRunId(rootRunId);
      return join(config.traceDir, `${rootRunId}.jsonl`);
    },
    async close() {
      if (closed) return;
      closed = true;
      for (const controller of activeControllers) {
        controller.abort(new RuntimeError("RUN_ABORTED", "Runtime was closed"));
      }
      await Promise.allSettled([...activeRuns]);
      const results = await Promise.allSettled([
        ...[...ownedRunners].map((runner) => runner.close()),
        mcp.close(),
      ]);
      const failure = results.find((result) => result.status === "rejected");
      if (failure?.status === "rejected") throw failure.reason;
    },
  };
}
