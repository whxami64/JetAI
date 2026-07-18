import { randomUUID } from "node:crypto";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import type { RuntimeTraceEventType } from "./types.js";

export async function trace(
  context: RuntimeContext,
  eventType: RuntimeTraceEventType,
  data: Record<string, unknown> = {},
): Promise<void> {
  try {
    await context.eventStore.append({
      eventId: randomUUID(),
      eventType,
      timestamp: new Date().toISOString(),
      rootRunId: context.rootRunId,
      runId: context.runId,
      ...(context.parentRunId === undefined ? {} : { parentRunId: context.parentRunId }),
      agentId: context.agentId,
      depth: context.depth,
      data,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown trace error";
    process.emitWarning(message, { code: "TRACE_WRITE_FAILED" });
  }
}
