import type { InlineExtension, ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { RuntimeConfig } from "../config/types.js";
import { RuntimeError } from "../errors.js";
import {
  createLifecycleTracingExtension,
  createStructuredResultCapture,
  createToolPolicyExtension,
} from "../extensions/index.js";
import type { SessionFactory } from "../runtime/create-pi-session.js";
import { SubagentSubmissionSchema, type SubagentResult } from "../schemas/agent-result.js";
import type { SubagentRunRequest, SubagentRunner } from "./runner.js";

export type ChildToolProvider = (request: SubagentRunRequest) => {
  tools: ToolDefinition[];
  extensions?: InlineExtension[];
};

function buildMetrics(
  startedAt: string,
  stats: ReturnType<Awaited<ReturnType<SessionFactory["create"]>>["stats"]>,
) {
  const completedAt = new Date().toISOString();
  return {
    startedAt,
    completedAt,
    durationMs: Date.parse(completedAt) - Date.parse(startedAt),
    ...stats,
  };
}

export class EmbeddedSubagentRunner implements SubagentRunner {
  readonly #sessions: SessionFactory;
  readonly #config: RuntimeConfig;
  readonly #toolProvider: ChildToolProvider;

  constructor(sessions: SessionFactory, config: RuntimeConfig, toolProvider: ChildToolProvider) {
    this.#sessions = sessions;
    this.#config = config;
    this.#toolProvider = toolProvider;
  }

  async run(request: SubagentRunRequest): Promise<SubagentResult> {
    const startedAt = new Date().toISOString();
    const submission = createStructuredResultCapture({
      name: "submit_subagent_result",
      label: "Submit subagent result",
      description: "Submit the validated specialist result",
      schema: SubagentSubmissionSchema,
      runtimeContext: request.runtimeContext,
    });
    const supplied = this.#toolProvider(request);
    const allowedTools = new Set([...request.agent.allowedTools, submission.tool.name]);
    const activeAgent = { ...request.agent, allowedTools: [...allowedTools] };
    const extensions = [
      createLifecycleTracingExtension(request.runtimeContext, request.agent.maxTurns),
      createToolPolicyExtension(allowedTools, request.runtimeContext, request.agent.canDelegate === true),
      ...(supplied.extensions ?? []),
    ];
    const session = await this.#sessions.create({
      agent: activeAgent,
      runtimeContext: request.runtimeContext,
      tools: [...supplied.tools, submission.tool],
      extensions,
      persistent: false,
    });
    try {
      const prompt = [
        `Parent run ID: ${request.runtimeContext.parentRunId ?? "none"}`,
        `Child run ID: ${request.runtimeContext.runId}`,
        `Objective: ${request.objective}`,
        `Explicit context: ${JSON.stringify(request.context ?? {})}`,
        request.expectedOutput === undefined ? "" : `Expected output: ${request.expectedOutput}`,
        "Use only the supplied context. Do not assume access to the parent transcript.",
        `Submit exactly one result using submit_subagent_result. Schema: ${JSON.stringify(SubagentSubmissionSchema)}`,
      ]
        .filter((line) => line !== "")
        .join("\n\n");
      await session.run(prompt, request.runtimeContext.signal);
      for (let attempt = 0; submission.get() === undefined && attempt < this.#config.limits.maxRetries; attempt += 1) {
        await session.run(
          "No valid result was submitted. Repair the output and call submit_subagent_result exactly once.",
          request.runtimeContext.signal,
        );
      }
      const payload = submission.get();
      if (payload === undefined) {
        throw new RuntimeError("RESULT_NOT_SUBMITTED", "Subagent did not submit a valid result");
      }
      if (JSON.stringify(payload).length > this.#config.limits.maxResultChars) {
        throw new RuntimeError("RESULT_INVALID", "Subagent result exceeds the configured size limit");
      }
      const metrics = buildMetrics(startedAt, session.stats());
      return {
        runId: request.runtimeContext.runId,
        parentRunId: request.runtimeContext.parentRunId ?? request.runtimeContext.rootRunId,
        agentId: request.agent.id,
        status: "completed",
        ...payload,
        metrics,
      };
    } finally {
      await session.close();
    }
  }

  async close(): Promise<void> {}
}
