import type { InlineExtension } from "@earendil-works/pi-coding-agent";
import type { RuntimeContext } from "../runtime/runtime-context.js";
import { trace } from "../tracing/trace.js";

export function createLifecycleTracingExtension(
  runtimeContext: RuntimeContext,
  maxTurns?: number,
): InlineExtension {
  return {
    name: "runtime-lifecycle-tracing",
    factory(pi) {
      pi.on("turn_start", async (event, context) => {
        await trace(runtimeContext, "turn.started", { turnIndex: event.turnIndex });
        if (maxTurns !== undefined && event.turnIndex >= maxTurns) context.abort();
      });
      pi.on("turn_end", (event) =>
        trace(runtimeContext, "turn.completed", {
          turnIndex: event.turnIndex,
          toolResultCount: event.toolResults.length,
        }),
      );
    },
  };
}
