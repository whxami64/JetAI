import { describe, expect, it } from "vitest";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import { createAgentRuntime } from "../runtime/create-agent-runtime.js";
import type {
  CreateSessionOptions,
  RuntimeSession,
  SessionFactory,
} from "../runtime/create-pi-session.js";
import { FakeSubagentRunner } from "../subagents/fake-runner.js";
import { MemoryEventStore } from "../tracing/event-store.js";
import { CODING_TOOL_NAMES } from "../extensions/tool-policy.js";
import { fakeResult, specialist, testConfig } from "./fixtures.js";

async function executeTool(tool: ToolDefinition, params: unknown, signal?: AbortSignal): Promise<void> {
  await tool.execute("fake-call", params, signal, undefined, {} as never);
}

class SupervisorSessionFactory implements SessionFactory {
  readonly activeToolSets: string[][] = [];
  readonly persistence: boolean[] = [];
  closeCount = 0;

  create(options: CreateSessionOptions): Promise<RuntimeSession> {
    this.activeToolSets.push([...options.agent.allowedTools]);
    this.persistence.push(options.persistent);
    let submitted = false;
    const tools = new Map(options.tools.map((tool) => [tool.name, tool]));
    return Promise.resolve({
      activeTools: [...options.agent.allowedTools],
      run: async (_prompt, signal) => {
        signal?.throwIfAborted();
        if (submitted || options.agent.id !== "supervisor") return;
        const parallel = tools.get("delegate_parallel");
        const submit = tools.get("submit_supervisor_result");
        if (parallel === undefined || submit === undefined) throw new Error("Missing runtime tools");
        await executeTool(
          parallel,
          {
            tasks: [
              { agentId: "specialist", objective: "one", context: { item: 1 } },
              { agentId: "specialist", objective: "two", context: { item: 2 } },
            ],
          },
          signal,
        );
        await executeTool(
          submit,
          { summary: "combined", findings: [], unresolvedQuestions: [] },
          signal,
        );
        submitted = true;
      },
      stats: () => ({
        turns: 1,
        toolCalls: 2,
        inputTokens: 10,
        outputTokens: 5,
        totalTokens: 15,
        estimatedCost: 0,
      }),
      close: () => {
        this.closeCount += 1;
        return Promise.resolve();
      },
    });
  }
}

describe("AgentRuntime", () => {
  it("runs a supervisor with parallel isolated children and no coding tools", async () => {
    const sessions = new SupervisorSessionFactory();
    const runner = new FakeSubagentRunner((request) =>
      Promise.resolve(fakeResult(request, request.objective)),
    );
    const runtime = await createAgentRuntime({
      config: testConfig(),
      agents: [specialist],
      sessionFactory: sessions,
      subagentRunner: runner,
      eventStoreFactory: () => new MemoryEventStore(),
    });
    const result = await runtime.run({ objective: "coordinate", context: { caseId: "demo" } });
    expect(result.status).toBe("completed");
    expect(result.subagentRuns.map((run) => run.summary)).toEqual(["one", "two"]);
    expect(runner.requests.map((request) => request.context)).toEqual([{ item: 1 }, { item: 2 }]);
    expect(sessions.activeToolSets[0]?.some((name) => CODING_TOOL_NAMES.has(name))).toBe(false);
    expect(sessions.persistence).toEqual([false]);
    expect(sessions.closeCount).toBe(1);
    await runtime.close();
    expect(runner.closed).toBe(true);
  });

  it("rejects unsafe run IDs before constructing a trace path", async () => {
    const runtime = await createAgentRuntime({
      config: testConfig(),
      sessionFactory: new SupervisorSessionFactory(),
      eventStoreFactory: () => new MemoryEventStore(),
    });
    await expect(runtime.run({ objective: "test", runId: "../../outside" })).rejects.toMatchObject({
      code: "CONFIG_INVALID",
    });
    expect(() => runtime.tracePath("../outside")).toThrow(/runId/);
    await runtime.close();
  });

  it("returns an aborted result for a pre-aborted root signal", async () => {
    const controller = new AbortController();
    controller.abort();
    const runtime = await createAgentRuntime({
      config: testConfig(),
      sessionFactory: new SupervisorSessionFactory(),
      eventStoreFactory: () => new MemoryEventStore(),
    });
    await expect(
      runtime.run({ objective: "test", signal: controller.signal }),
    ).resolves.toMatchObject({ status: "aborted", error: { code: "RUN_ABORTED" } });
    await runtime.close();
  });
});
