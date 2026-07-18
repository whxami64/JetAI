import { resolve } from "node:path";
import { RuntimeError } from "../errors.js";
import { DEFAULT_LIMITS, type RuntimeConfig } from "./types.js";

function integerAtLeast(
  env: NodeJS.ProcessEnv,
  name: string,
  fallback: number,
  minimum: number,
): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new RuntimeError("CONFIG_INVALID", `${name} must be an integer of at least ${minimum}`);
  }
  return value;
}

function thinkingLevel(value: string | undefined): RuntimeConfig["model"]["thinkingLevel"] {
  const level = value ?? "medium";
  if (["off", "minimal", "low", "medium", "high", "xhigh"].includes(level)) {
    return level as RuntimeConfig["model"]["thinkingLevel"];
  }
  throw new RuntimeError("CONFIG_INVALID", "PI_THINKING_LEVEL is invalid");
}

export function loadRuntimeConfig(
  env: NodeJS.ProcessEnv = process.env,
  cwd = process.cwd(),
): RuntimeConfig {
  const provider = env.PI_PROVIDER?.trim() || undefined;
  const model = env.PI_MODEL?.trim() || undefined;
  return {
    cwd,
    model: {
      ...(provider === undefined ? {} : { provider }),
      ...(model === undefined ? {} : { model }),
      thinkingLevel: thinkingLevel(env.PI_THINKING_LEVEL),
    },
    limits: {
      maxDelegationDepth: integerAtLeast(
        env,
        "AGENT_MAX_DELEGATION_DEPTH",
        DEFAULT_LIMITS.maxDelegationDepth,
        0,
      ),
      maxParallelSubagents: integerAtLeast(
        env,
        "AGENT_MAX_PARALLEL_SUBAGENTS",
        DEFAULT_LIMITS.maxParallelSubagents,
        1,
      ),
      maxDelegatedTasks: integerAtLeast(
        env,
        "AGENT_MAX_DELEGATED_TASKS",
        DEFAULT_LIMITS.maxDelegatedTasks,
        0,
      ),
      subagentTimeoutMs: integerAtLeast(
        env,
        "AGENT_SUBAGENT_TIMEOUT_MS",
        DEFAULT_LIMITS.subagentTimeoutMs,
        1,
      ),
      maxRetries: integerAtLeast(env, "AGENT_MAX_RETRIES", DEFAULT_LIMITS.maxRetries, 0),
      maxResultChars: integerAtLeast(
        env,
        "AGENT_MAX_RESULT_CHARS",
        DEFAULT_LIMITS.maxResultChars,
        1,
      ),
    },
    sessionDir: resolve(cwd, env.AGENT_SESSION_DIR ?? ".runtime/sessions"),
    traceDir: resolve(cwd, env.AGENT_TRACE_DIR ?? ".runtime/traces"),
    mcp: {
      enabled: env.AGENT_MCP_ENABLED === "true",
      configPath: resolve(cwd, env.AGENT_MCP_CONFIG ?? ".config/mcp.json"),
    },
  };
}
