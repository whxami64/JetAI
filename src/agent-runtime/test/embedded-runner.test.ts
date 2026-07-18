import { describe, expect, it } from "vitest";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import { EmbeddedSubagentRunner } from "../subagents/embedded-runner.js";
import type {
  CreateSessionOptions,
  RuntimeSession,
  SessionFactory,
} from "../runtime/create-pi-session.js";
import { childRuntimeContext } from "../runtime/runtime-context.js";
import { specialist, testConfig, testContext } from "./fixtures.js";

class RepairSessionFactory implements SessionFactory {
  readonly prompts: string[] = [];
  closeCount = 0;
  readonly #submitOnRun: number | undefined;

  constructor(submitOnRun?: number) {
    this.#submitOnRun = submitOnRun;
  }

  create(options: CreateSessionOptions): Promise<RuntimeSession> {
    let runs = 0;
    const submit = options.tools.find((tool) => tool.name === "submit_subagent_result");
    return Promise.resolve({
      activeTools: [...options.agent.allowedTools],
      run: async (prompt, signal) => {
        this.prompts.push(prompt);
        runs += 1;
        if (runs === this.#submitOnRun) {
          if (submit === undefined) throw new Error("Missing submit tool");
          await submit.execute(
            "submit",
            {
              summary: "repaired",
              findings: [],
              evidence: [],
              unresolvedQuestions: [],
            },
            signal,
            undefined,
            {} as never,
          );
        }
      },
      stats: () => ({
        turns: runs,
        toolCalls: submit === undefined ? 0 : 1,
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
        estimatedCost: 0,
      }),
      close: () => {
        this.closeCount += 1;
        return Promise.resolve();
      },
    });
  }
}

function requestContext() {
  return childRuntimeContext(testContext(), "child", specialist.id);
}

describe("EmbeddedSubagentRunner", () => {
  it("allows one repair prompt and closes the isolated session", async () => {
    const sessions = new RepairSessionFactory(2);
    const runner = new EmbeddedSubagentRunner(sessions, testConfig({ maxRetries: 1 }), () => ({
      tools: [] as ToolDefinition[],
    }));
    const result = await runner.run({
      agent: specialist,
      objective: "inspect",
      context: { visible: true },
      runtimeContext: requestContext(),
    });
    expect(result).toMatchObject({ status: "completed", summary: "repaired" });
    expect(sessions.prompts).toHaveLength(2);
    expect(sessions.prompts[0]).toContain('"visible":true');
    expect(sessions.closeCount).toBe(1);
  });

  it("fails after the repair budget is exhausted and still closes", async () => {
    const sessions = new RepairSessionFactory();
    const runner = new EmbeddedSubagentRunner(sessions, testConfig({ maxRetries: 1 }), () => ({
      tools: [],
    }));
    await expect(
      runner.run({
        agent: specialist,
        objective: "inspect",
        runtimeContext: requestContext(),
      }),
    ).rejects.toMatchObject({ code: "RESULT_NOT_SUBMITTED" });
    expect(sessions.prompts).toHaveLength(2);
    expect(sessions.closeCount).toBe(1);
  });
});
