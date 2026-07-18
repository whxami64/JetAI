import { RuntimeError } from "../errors.js";
import type { AgentDefinition } from "./types.js";

const THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh"]);

export interface AgentRegistryOptions {
  knownTools: ReadonlySet<string>;
  delegationEnabled?: boolean;
}

export class AgentRegistry {
  readonly #agents = new Map<string, AgentDefinition>();

  constructor(definitions: AgentDefinition[], options: AgentRegistryOptions) {
    for (const definition of definitions) {
      this.#validate(definition, options);
      if (this.#agents.has(definition.id)) {
        throw new RuntimeError(
          "AGENT_REGISTRY_INVALID",
          `Duplicate agent ID: ${definition.id}`,
        );
      }
      this.#agents.set(definition.id, structuredClone(definition));
    }
  }

  get(id: string): AgentDefinition {
    const definition = this.#agents.get(id);
    if (definition === undefined) {
      throw new RuntimeError("AGENT_NOT_FOUND", `Unknown subagent: ${id}`);
    }
    return structuredClone(definition);
  }

  list(): AgentDefinition[] {
    return [...this.#agents.values()].map((definition) => structuredClone(definition));
  }

  #validate(definition: AgentDefinition, options: AgentRegistryOptions): void {
    if (!/^[a-z][a-z0-9_-]*$/.test(definition.id)) {
      throw new RuntimeError("AGENT_REGISTRY_INVALID", `Invalid agent ID: ${definition.id}`);
    }
    if (definition.description.trim() === "" || definition.systemPrompt.trim() === "") {
      throw new RuntimeError(
        "AGENT_REGISTRY_INVALID",
        `Agent ${definition.id} requires a description and system prompt`,
      );
    }
    for (const tool of definition.allowedTools) {
      if (!options.knownTools.has(tool)) {
        throw new RuntimeError(
          "AGENT_REGISTRY_INVALID",
          `Agent ${definition.id} references unknown tool: ${tool}`,
        );
      }
    }
    if (definition.canDelegate === true && options.delegationEnabled === false) {
      throw new RuntimeError(
        "AGENT_REGISTRY_INVALID",
        `Agent ${definition.id} cannot delegate when delegation is disabled`,
      );
    }
    const override = definition.model;
    if (override !== undefined) {
      if (override.provider !== undefined && override.provider.trim() === "") {
        throw new RuntimeError("AGENT_REGISTRY_INVALID", `Agent ${definition.id} has an empty provider`);
      }
      if (override.model !== undefined && override.model.trim() === "") {
        throw new RuntimeError("AGENT_REGISTRY_INVALID", `Agent ${definition.id} has an empty model`);
      }
      if (override.thinkingLevel !== undefined && !THINKING_LEVELS.has(override.thinkingLevel)) {
        throw new RuntimeError(
          "AGENT_REGISTRY_INVALID",
          `Agent ${definition.id} has an invalid thinking level`,
        );
      }
    }
    if (definition.maxTurns !== undefined && definition.maxTurns < 1) {
      throw new RuntimeError("AGENT_REGISTRY_INVALID", `Agent ${definition.id} has invalid maxTurns`);
    }
    if (definition.timeoutMs !== undefined && definition.timeoutMs < 1) {
      throw new RuntimeError("AGENT_REGISTRY_INVALID", `Agent ${definition.id} has invalid timeoutMs`);
    }
  }
}
