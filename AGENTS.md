# JetAI Agent Runtime Guide

## Purpose And Scope

JetAI is building a controlled agent foundation for future Journal Entry Testing. The current M0
scope is runtime infrastructure only: embedded Pi sessions, explicit tools, isolated delegation,
structured results, tracing, limits, and optional MCP clients. Do not add audit workflows,
specialists, findings logic, document preprocessing, persistence schemas, or integrations yet.

The existing Python package remains responsible for dataset-oriented code. The independent
TypeScript runtime lives in `src/agent-runtime/` and is managed with pnpm.

## Architecture

- `runtime/`: public runtime and isolated Pi session factory.
- `agents/`: declarative definitions and registry validation. No production specialists exist yet.
- `subagents/`: replaceable runner, scheduler, delegation service, and deterministic fake.
- `tools/`: supervisor delegation tools.
- `extensions/`: lifecycle tracing, result capture, and tool-policy interception.
- `tracing/`: serialized, redacted JSONL events under `.runtime/traces/`.
- `mcp/`: opt-in stdio/Streamable HTTP clients and primitive-schema tool adapter.
- `schemas/`: TypeBox contracts for all model-produced results.

## Commands

- `pnpm agent:typecheck`: strict TypeScript check.
- `pnpm agent:lint`: ESLint checks.
- `pnpm agent:test`: offline tests; never calls a model provider.
- `pnpm agent:test:watch`: watch offline tests.
- `pnpm agent:demo`: live generic supervisor demo; requires provider/model configuration.
- `pnpm agent:smoke`: same live integration entry point for CI/manual smoke validation.
- `uv run pytest`: Python tests.

## Security Rules

- Product sessions must pass an exact `tools` allowlist to Pi and verify active tool names.
- Never enable Pi's `bash`, `edit`, `find`, `grep`, `ls`, `read`, or `write` tools in product mode.
- A tool must pass both session allowlisting and the interception policy.
- Never put credentials in prompts, sessions, traces, `.pi/settings.json`, or MCP configuration.
- MCP stays disabled unless `AGENT_MCP_ENABLED=true`; connect only to reviewed configured servers.
- Do not make model output trusted by assertion or parsing alone. Validate it with TypeBox.
- Offline tests must not call paid APIs. Live smoke success may only be reported after a real run.

## Extension Points

To add a specialist, define an `AgentDefinition`, explicitly list known safe tool names, and pass it
to `createAgentRuntime({ agents: [...] })`. Add registry, policy, isolation, and result tests.

To add a local tool, implement a Pi `ToolDefinition` with a TypeBox parameter schema, pass it in
`applicationTools`, and explicitly allow it only on agents that require it. Never alias a coding tool.

To add an MCP server, add a reviewed disabled entry to `.config/mcp.json`, verify its transport and
schema support, then opt in locally with `AGENT_MCP_ENABLED=true`. Imported names use
`mcp__<serverId>__<toolName>` and still require an agent allowlist entry.
