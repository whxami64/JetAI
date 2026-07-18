import type { JsonSchemaType } from "@modelcontextprotocol/sdk/validation";

export interface StdioMcpServerConfig {
  enabled: boolean;
  transport: "stdio";
  command: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}

export interface HttpMcpServerConfig {
  enabled: boolean;
  transport: "streamable-http";
  url: string;
  headers?: Record<string, string>;
}

export type McpServerConfig = StdioMcpServerConfig | HttpMcpServerConfig;

export interface McpConfigFile {
  servers: Record<string, McpServerConfig>;
}

export interface McpRemoteTool {
  name: string;
  title?: string;
  description?: string;
  inputSchema: JsonSchemaType;
}

export interface McpConnection {
  listTools(signal?: AbortSignal): Promise<McpRemoteTool[]>;
  callTool(name: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<unknown>;
  close(): Promise<void>;
}

export type McpConnectionFactory = (
  serverId: string,
  config: McpServerConfig,
  signal?: AbortSignal,
) => Promise<McpConnection>;
