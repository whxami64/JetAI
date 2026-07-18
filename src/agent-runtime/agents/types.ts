export interface AgentModelOverride {
  provider?: string;
  model?: string;
  thinkingLevel?: "off" | "minimal" | "low" | "medium" | "high" | "xhigh";
}

export interface AgentDefinition {
  id: string;
  description: string;
  systemPrompt: string;
  allowedTools: string[];
  model?: AgentModelOverride;
  maxTurns?: number;
  timeoutMs?: number;
  canDelegate?: boolean;
}
