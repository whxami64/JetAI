import { describe, expect, it } from "vitest";
import { AgentRegistry } from "../agents/registry.js";
import type { AgentDefinition } from "../agents/types.js";
import { delegator, specialist } from "./fixtures.js";

const tools = new Set(["list_subagents", "delegate_to_subagent", "delegate_parallel"]);

describe("AgentRegistry", () => {
  it("accepts valid definitions and returns defensive copies", () => {
    const registry = new AgentRegistry([specialist], { knownTools: tools });
    const first = registry.get("specialist");
    first.systemPrompt = "changed";
    expect(registry.get("specialist").systemPrompt).toBe(specialist.systemPrompt);
  });

  it("rejects duplicate IDs", () => {
    expect(() => new AgentRegistry([specialist, specialist], { knownTools: tools })).toThrow(
      /Duplicate agent ID/,
    );
  });

  it("rejects missing prompts", () => {
    const invalid: AgentDefinition = { ...specialist, systemPrompt: "" };
    expect(() => new AgentRegistry([invalid], { knownTools: tools })).toThrow(/requires/);
  });

  it("rejects unknown tools", () => {
    const invalid: AgentDefinition = { ...specialist, allowedTools: ["bash"] };
    expect(() => new AgentRegistry([invalid], { knownTools: tools })).toThrow(/unknown tool/);
  });

  it("rejects invalid model overrides", () => {
    const invalid: AgentDefinition = { ...specialist, model: { provider: "" } };
    expect(() => new AgentRegistry([invalid], { knownTools: tools })).toThrow(/empty provider/);
  });

  it("rejects delegation when globally disabled", () => {
    expect(
      () => new AgentRegistry([delegator], { knownTools: tools, delegationEnabled: false }),
    ).toThrow(/cannot delegate/);
  });
});
