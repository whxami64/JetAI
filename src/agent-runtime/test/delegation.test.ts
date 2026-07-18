import { describe, expect, it } from "vitest";
import { AgentRegistry } from "../agents/registry.js";
import { DelegationService } from "../subagents/delegation-service.js";
import { FakeSubagentRunner } from "../subagents/fake-runner.js";
import { RuntimeError } from "../errors.js";
import { delegator, fakeResult, specialist, testConfig, testContext } from "./fixtures.js";

const knownTools = new Set(["list_subagents", "delegate_to_subagent", "delegate_parallel"]);

function setup(
  runner = new FakeSubagentRunner((request) => Promise.resolve(fakeResult(request))),
  limits: Partial<ReturnType<typeof testConfig>["limits"]> = {},
) {
  const registry = new AgentRegistry([specialist, delegator], { knownTools });
  return {
    runner,
    service: new DelegationService(registry, runner, testConfig(limits).limits),
  };
}

describe("DelegationService", () => {
  it("creates isolated child metadata and forwards only explicit context", async () => {
    const { runner, service } = setup();
    const result = await service.delegate(delegator, testContext(), {
      agentId: "specialist",
      objective: "inspect",
      context: { allowed: true },
    });
    expect(result.parentRunId).toBe("parent-run");
    expect(result.runId).not.toBe("parent-run");
    expect(runner.requests[0]?.context).toEqual({ allowed: true });
    expect(runner.requests[0]?.runtimeContext).toMatchObject({
      rootRunId: "root-run",
      parentRunId: "parent-run",
      depth: 1,
    });
  });

  it("blocks non-delegating agents", async () => {
    const { service } = setup();
    await expect(
      service.delegate(specialist, testContext({ agent: specialist }), {
        agentId: "specialist",
        objective: "blocked",
      }),
    ).rejects.toMatchObject({ code: "DELEGATION_NOT_ALLOWED" });
  });

  it("enforces depth and total task budget", async () => {
    const { service } = setup();
    await expect(
      service.delegate(delegator, testContext({ depth: 2 }), {
        agentId: "specialist",
        objective: "too deep",
      }),
    ).rejects.toMatchObject({ code: "DELEGATION_DEPTH_EXCEEDED" });
    await expect(
      service.delegateParallel(delegator, testContext({ maximum: 1 }), [
        { agentId: "specialist", objective: "one" },
        { agentId: "specialist", objective: "two" },
      ]),
    ).rejects.toMatchObject({ code: "DELEGATION_BUDGET_EXCEEDED" });
  });

  it("bounds concurrency and preserves input order", async () => {
    let active = 0;
    let peak = 0;
    const runner = new FakeSubagentRunner(async (request) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, request.objective === "first" ? 20 : 5));
      active -= 1;
      return fakeResult(request, request.objective);
    });
    const { service } = setup(runner, { maxParallelSubagents: 2 });
    const results = await service.delegateParallel(delegator, testContext(), [
      { agentId: "specialist", objective: "first" },
      { agentId: "specialist", objective: "second" },
      { agentId: "specialist", objective: "third" },
    ]);
    expect(peak).toBe(2);
    expect(results.map((result) => result.summary)).toEqual(["first", "second", "third"]);
  });

  it("keeps sibling success when another child fails", async () => {
    const runner = new FakeSubagentRunner((request) => {
      if (request.objective === "fail") throw new RuntimeError("RESULT_INVALID", "bad child");
      return Promise.resolve(fakeResult(request));
    });
    const { service } = setup(runner);
    const results = await service.delegateParallel(delegator, testContext(), [
      { agentId: "specialist", objective: "pass" },
      { agentId: "specialist", objective: "fail" },
    ]);
    expect(results.map((result) => result.status)).toEqual(["completed", "failed"]);
  });

  it("returns typed timeout and releases the scheduler slot", async () => {
    const runner = new FakeSubagentRunner(async (request) => {
      await new Promise<void>((_resolve, reject) => {
        request.runtimeContext.signal?.addEventListener(
          "abort",
          () => {
            const reason: unknown = request.runtimeContext.signal?.reason;
            reject(reason instanceof Error ? reason : new Error("Subagent aborted"));
          },
          { once: true },
        );
      });
      return fakeResult(request);
    });
    const { service } = setup(runner, { subagentTimeoutMs: 10, maxParallelSubagents: 1 });
    const first = await service.delegate(delegator, testContext(), {
      agentId: "specialist",
      objective: "timeout",
    });
    expect(first.status).toBe("timed_out");
    const replacement = new FakeSubagentRunner((request) => Promise.resolve(fakeResult(request)));
    const next = setup(replacement, { maxParallelSubagents: 1 }).service;
    await expect(
      next.delegate(delegator, testContext(), { agentId: "specialist", objective: "next" }),
    ).resolves.toMatchObject({ status: "completed" });
  });

  it("propagates a parent abort to every active child", async () => {
    const started: string[] = [];
    const runner = new FakeSubagentRunner(async (request) => {
      started.push(request.objective);
      await new Promise<void>((_resolve, reject) => {
        request.runtimeContext.signal?.addEventListener(
          "abort",
          () => reject(new RuntimeError("RUN_ABORTED", "parent aborted")),
          { once: true },
        );
      });
      return fakeResult(request);
    });
    const controller = new AbortController();
    const { service } = setup(runner, { maxParallelSubagents: 2 });
    const pending = service.delegateParallel(
      delegator,
      testContext({ signal: controller.signal }),
      [
        { agentId: "specialist", objective: "one" },
        { agentId: "specialist", objective: "two" },
      ],
    );
    while (started.length < 2) await new Promise((resolve) => setTimeout(resolve, 1));
    controller.abort();
    const results = await pending;
    expect(results.map((result) => result.status)).toEqual(["aborted", "aborted"]);
  });

  it("rejects mismatched metadata from a replaceable runner", async () => {
    const runner = new FakeSubagentRunner((request) =>
      Promise.resolve({ ...fakeResult(request), runId: "forged" }),
    );
    const { service } = setup(runner);
    await expect(
      service.delegate(delegator, testContext(), {
        agentId: "specialist",
        objective: "inspect",
      }),
    ).resolves.toMatchObject({
      status: "failed",
      error: { code: "RESULT_INVALID" },
    });
  });
});
