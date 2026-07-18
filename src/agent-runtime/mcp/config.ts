import { readFile } from "node:fs/promises";
import { Type } from "typebox";
import { RuntimeError } from "../errors.js";
import { validateValue } from "../schemas/validate.js";
import type { McpConfigFile } from "./types.js";

const StringRecord = Type.Record(Type.String(), Type.String());
const ServerSchema = Type.Union([
  Type.Object(
    {
      enabled: Type.Boolean(),
      transport: Type.Literal("stdio"),
      command: Type.String({ minLength: 1 }),
      args: Type.Optional(Type.Array(Type.String())),
      env: Type.Optional(StringRecord),
      cwd: Type.Optional(Type.String()),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      enabled: Type.Boolean(),
      transport: Type.Literal("streamable-http"),
      url: Type.String({ minLength: 1 }),
      headers: Type.Optional(StringRecord),
    },
    { additionalProperties: false },
  ),
]);
const McpConfigSchema = Type.Object(
  { servers: Type.Record(Type.String(), ServerSchema) },
  { additionalProperties: false },
);

export async function loadMcpConfig(path: string): Promise<McpConfigFile> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new RuntimeError("CONFIG_INVALID", `Unable to read MCP config at ${path}`, { cause: error });
  }
  return validateValue(McpConfigSchema, parsed, "MCP configuration");
}
