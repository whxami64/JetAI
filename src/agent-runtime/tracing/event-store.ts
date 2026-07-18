import type { RuntimeTraceEvent } from "./types.js";

export interface EventStore {
  append(event: RuntimeTraceEvent): Promise<void>;
  close(): Promise<void>;
}

export class MemoryEventStore implements EventStore {
  readonly events: RuntimeTraceEvent[] = [];

  append(event: RuntimeTraceEvent): Promise<void> {
    this.events.push(structuredClone(event));
    return Promise.resolve();
  }

  async close(): Promise<void> {}
}
