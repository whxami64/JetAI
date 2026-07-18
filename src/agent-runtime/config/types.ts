export interface RuntimeLimits {
  maxDelegationDepth: number;
  maxParallelSubagents: number;
  maxDelegatedTasks: number;
  subagentTimeoutMs: number;
  maxRetries: number;
  maxResultChars: number;
}

export interface ModelConfig {
  provider?: string;
  model?: string;
  thinkingLevel: "off" | "minimal" | "low" | "medium" | "high" | "xhigh";
}

export interface McpRuntimeConfig {
  enabled: boolean;
  configPath: string;
}

export interface RuntimeConfig {
  cwd: string;
  model: ModelConfig;
  limits: RuntimeLimits;
  sessionDir: string;
  traceDir: string;
  mcp: McpRuntimeConfig;
}

export const DEFAULT_LIMITS: RuntimeLimits = {
  maxDelegationDepth: 2,
  maxParallelSubagents: 4,
  maxDelegatedTasks: 8,
  subagentTimeoutMs: 120_000,
  maxRetries: 1,
  maxResultChars: 20_000,
};
