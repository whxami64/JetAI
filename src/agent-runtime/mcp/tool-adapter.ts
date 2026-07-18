import { defineTool, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { AjvJsonSchemaValidator } from "@modelcontextprotocol/sdk/validation/ajv";
import { Type, type TProperties, type TSchema } from "typebox";
import { RuntimeError } from "../errors.js";
import type { McpConnection, McpRemoteTool } from "./types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function adaptSchema(schema: unknown): TSchema {
  if (!isRecord(schema) || typeof schema.type !== "string") {
    throw new RuntimeError("MCP_TOOL_SCHEMA_UNSUPPORTED", "MCP schema must declare a primitive type");
  }
  switch (schema.type) {
    case "string":
      return Type.String();
    case "number":
      return Type.Number();
    case "integer":
      return Type.Integer();
    case "boolean":
      return Type.Boolean();
    case "array":
      return Type.Array(adaptSchema(schema.items));
    case "object": {
      if (!isRecord(schema.properties)) {
        return Type.Object({}, { additionalProperties: false });
      }
      const required = new Set(
        Array.isArray(schema.required)
          ? schema.required.filter((item): item is string => typeof item === "string")
          : [],
      );
      const properties: TProperties = {};
      for (const [key, child] of Object.entries(schema.properties)) {
        const adapted = adaptSchema(child);
        properties[key] = required.has(key) ? adapted : Type.Optional(adapted);
      }
      return Type.Object(properties, { additionalProperties: false });
    }
    default:
      throw new RuntimeError(
        "MCP_TOOL_SCHEMA_UNSUPPORTED",
        `Unsupported MCP schema type: ${schema.type}`,
      );
  }
}

export function adaptMcpTool(
  serverId: string,
  remote: McpRemoteTool,
  connection: McpConnection,
): ToolDefinition {
  const parameters = adaptSchema(remote.inputSchema);
  const validate = new AjvJsonSchemaValidator().getValidator<Record<string, unknown>>(
    remote.inputSchema,
  );
  return defineTool({
    name: `mcp__${serverId}__${remote.name}`,
    label: remote.title ?? remote.name,
    description: remote.description ?? `Call ${remote.name} on MCP server ${serverId}`,
    parameters,
    async execute(_toolCallId, args, signal) {
      const checked = validate(args);
      if (!checked.valid) {
        throw new RuntimeError(
          "MCP_TOOL_SCHEMA_UNSUPPORTED",
          `Invalid MCP arguments: ${checked.errorMessage}`,
        );
      }
      const result = await connection.callTool(remote.name, checked.data, signal);
      if (isRecord(result) && result.isError === true) {
        throw new RuntimeError("MCP_CONNECTION_FAILED", `MCP tool ${remote.name} returned an error`);
      }
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: { result },
      };
    },
  });
}
