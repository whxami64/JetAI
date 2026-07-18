import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { McpClientManager } from "../mcp/client-manager.js";
import type { McpConnection, McpConnectionFactory } from "../mcp/types.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("McpClientManager", () => {
  it("creates no clients when MCP is disabled", async () => {
    let calls = 0;
    const factory: McpConnectionFactory = () => {
      calls += 1;
      throw new Error("must not connect");
    };
    const manager = new McpClientManager({ enabled: false, configPath: "missing.json" }, factory);
    await expect(manager.loadTools()).resolves.toEqual([]);
    expect(calls).toBe(0);
  });

  it("namespaces tools, validates calls, and closes transports", async () => {
    const directory = await mkdtemp(join(tmpdir(), "jetai-mcp-"));
    directories.push(directory);
    const configPath = join(directory, "mcp.json");
    await writeFile(
      configPath,
      JSON.stringify({
        servers: {
          demo: { enabled: true, transport: "stdio", command: "not-executed" },
        },
      }),
    );
    let closed = false;
    let received: Record<string, unknown> | undefined;
    const connection: McpConnection = {
      listTools: () => Promise.resolve([
        {
          name: "lookup",
          description: "Lookup a value",
          inputSchema: {
            type: "object",
            properties: { key: { type: "string" } },
            required: ["key"],
          },
        },
      ]),
      callTool: (_name, args) => {
        received = args;
        return Promise.resolve({ value: "found" });
      },
      close: () => {
        closed = true;
        return Promise.resolve();
      },
    };
    const manager = new McpClientManager(
      { enabled: true, configPath },
      () => Promise.resolve(connection),
    );
    const tools = await manager.loadTools();
    expect(tools.map((tool) => tool.name)).toEqual(["mcp__demo__lookup"]);
    await tools[0]?.execute("call", { key: "x" }, undefined, undefined, {} as never);
    expect(received).toEqual({ key: "x" });
    await manager.close();
    expect(closed).toBe(true);
  });

  it("closes a connection when tool discovery fails", async () => {
    const directory = await mkdtemp(join(tmpdir(), "jetai-mcp-"));
    directories.push(directory);
    const configPath = join(directory, "mcp.json");
    await writeFile(
      configPath,
      JSON.stringify({
        servers: { demo: { enabled: true, transport: "stdio", command: "unused" } },
      }),
    );
    let closed = false;
    const manager = new McpClientManager(
      { enabled: true, configPath },
      () => Promise.resolve({
        listTools: () => Promise.reject(new Error("discovery failed")),
        callTool: () => Promise.resolve({}),
        close: () => {
          closed = true;
          return Promise.resolve();
        },
      }),
    );
    await expect(manager.loadTools()).rejects.toThrow(/discovery failed/);
    expect(closed).toBe(true);
  });
});
