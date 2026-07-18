# Agent Runtime

This directory contains JetAI's domain-neutral M0 agent harness. It embeds the current
`@earendil-works/pi-coding-agent` SDK in-process; it does not invoke Pi through RPC and does not load
Pi's default coding tools or discovered project/global resources.

## Architecture

`createAgentRuntime()` creates an in-memory supervisor session per root run by default. Persistence
can be explicitly enabled with `persistentSupervisor: true`. Every delegated task
gets a fresh in-memory Pi session, focused system prompt, explicit context only, independent tool
allowlist, child run ID, timeout, and cancellation signal. `DelegationService` applies depth and
shared task-budget checks before scheduling work. Parallel results preserve request order and retain
successful siblings when another child fails.

Subagents finish by calling `submit_subagent_result`; the supervisor calls
`submit_supervisor_result`. TypeBox validates these submissions and the runtime adds authoritative
IDs, statuses, metrics, and child summaries. The runner abstraction can later be replaced by workers
or subprocesses without changing delegation tool contracts.

## Configuration

Copy values from `.env.example` into an untracked `.env`. A live run requires `PI_PROVIDER`,
`PI_MODEL`, and credentials supported by that provider. There is intentionally no hardcoded model.
All delegation, concurrency, timeout, retry, output-size, session, trace, and MCP settings are read
from the documented environment variables.

## Usage

```ts
import { createAgentRuntime, loadRuntimeConfig } from "./src/agent-runtime/index.js";

const runtime = await createAgentRuntime({
  config: loadRuntimeConfig(),
  agents: [],
});

const result = await runtime.run({
  objective: "Investigate the supplied case",
  context: { caseId: "demo-001" },
});

await runtime.close();
```

No production specialists are registered in M0. Supply reviewed `AgentDefinition` objects when the
next milestone defines actual responsibilities and tools.

## Commands

```text
pnpm agent:typecheck
pnpm agent:lint
pnpm agent:test
pnpm agent:demo
pnpm agent:smoke
```

The tests use fake sessions, subagents, and MCP connections and never call a model provider. The
demo/smoke command is live, prints the validated JSON result and trace path, and exits nonzero on a
failed or invalid result.

## Tracing And Policy

Events are serialized to `.runtime/traces/<rootRunId>.jsonl`. Secret-like fields are redacted,
hidden reasoning fields are omitted, and oversized strings are truncated. A trace write failure is
surfaced as a process warning without changing an otherwise successful model result.

Every session receives an explicit Pi allowlist and verifies the resulting active tool names after
extension binding. A separate `tool_call` interception hook blocks unknown tools, all coding tools,
and delegation by non-delegating agents.

## MCP

MCP is disabled by default. When enabled, the manager supports reviewed stdio and Streamable HTTP
servers from `.config/mcp.json`, namespaces tools, validates arguments with the MCP SDK, forwards
cancellation, and closes all clients. The current adapter intentionally supports object schemas made
from string, number, integer, boolean, array, and nested object properties only. Unsupported JSON
Schema features fail with `MCP_TOOL_SCHEMA_UNSUPPORTED` rather than weakening validation.

## Known Limitations

- No concrete specialists or workflows are registered, per the current implementation request.
- The live demo therefore validates the supervisor/session foundation but cannot demonstrate two
  real specialist definitions until they are approved in a later milestone.
- Pi `0.80.10` requires Node `>=22.19`; the dev container uses Node 24.
- The official split MCP v2 client remains beta, so this runtime uses stable MCP SDK v1.29.
- Pi does not accept an `AbortSignal` in `prompt()`; the session adapter bridges aborts to
  `session.abort()`.
- Replaceable in-process `SubagentRunner` implementations must honor the supplied abort signal;
  forcibly terminating non-cooperative JavaScript requires a future worker/process runner.
