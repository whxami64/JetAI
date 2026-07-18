import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { RuntimeError } from "../errors.js";
import type { McpRuntimeConfig } from "../config/types.js";
import { loadMcpConfig } from "./config.js";
import { adaptMcpTool } from "./tool-adapter.js";
import type {
  McpConnection,
  McpConnectionFactory,
  McpRemoteTool,
  McpServerConfig,
} from "./types.js";

async function createConnection(
  _serverId: string,
  config: McpServerConfig,
  signal?: AbortSignal,
): Promise<McpConnection> {
  const client = new Client(
    { name: "jetai-agent-runtime", version: "0.1.0" },
    { capabilities: {} },
  );
  const transport = config.transport === "stdio"
    ? new StdioClientTransport({
        command: config.command,
        ...(config.args === undefined ? {} : { args: config.args }),
        env: { ...getDefaultEnvironment(), ...(config.env ?? {}) },
        ...(config.cwd === undefined ? {} : { cwd: config.cwd }),
        stderr: "inherit",
      })
    : new StreamableHTTPClientTransport(new URL(config.url), {
        requestInit: config.headers === undefined ? {} : { headers: config.headers },
      });
  try {
    await client.connect(transport, { signal, timeout: 30_000 });
  } catch (error) {
    await client.close().catch(() => undefined);
    throw new RuntimeError("MCP_CONNECTION_FAILED", "Failed to connect to MCP server", {
      cause: error,
    });
  }
  return {
    async listTools(toolSignal) {
      const result = await client.listTools(undefined, { signal: toolSignal });
      return result.tools.map((tool): McpRemoteTool => ({
        name: tool.name,
        ...(tool.title === undefined ? {} : { title: tool.title }),
        ...(tool.description === undefined ? {} : { description: tool.description }),
        inputSchema: tool.inputSchema,
      }));
    },
    async callTool(name, args, toolSignal) {
      return client.callTool({ name, arguments: args }, undefined, {
        signal: toolSignal,
        timeout: 60_000,
      });
    },
    async close() {
      await client.close();
    },
  };
}

export class McpClientManager {
  readonly #runtimeConfig: McpRuntimeConfig;
  readonly #factory: McpConnectionFactory;
  readonly #connections: McpConnection[] = [];

  constructor(runtimeConfig: McpRuntimeConfig, factory: McpConnectionFactory = createConnection) {
    this.#runtimeConfig = runtimeConfig;
    this.#factory = factory;
  }

  async loadTools(signal?: AbortSignal): Promise<ToolDefinition[]> {
    if (!this.#runtimeConfig.enabled) return [];
    try {
      const config = await loadMcpConfig(this.#runtimeConfig.configPath);
      const tools: ToolDefinition[] = [];
      for (const [serverId, server] of Object.entries(config.servers)) {
        if (!server.enabled) continue;
        const connection = await this.#factory(serverId, server, signal);
        this.#connections.push(connection);
        const remoteTools = await connection.listTools(signal);
        tools.push(...remoteTools.map((remote) => adaptMcpTool(serverId, remote, connection)));
      }
      return tools;
    } catch (error) {
      await this.close().catch(() => undefined);
      throw error;
    }
  }

  async close(): Promise<void> {
    const results = await Promise.allSettled(this.#connections.map((connection) => connection.close()));
    this.#connections.length = 0;
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") {
      throw new RuntimeError("MCP_CONNECTION_FAILED", "Failed to close an MCP connection", {
        cause: failure.reason,
      });
    }
  }
}
