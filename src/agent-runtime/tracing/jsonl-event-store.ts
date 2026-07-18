import { mkdir, appendFile } from "node:fs/promises";
import { dirname } from "node:path";
import { RuntimeError } from "../errors.js";
import type { EventStore } from "./event-store.js";
import { sanitizeTraceValue } from "./redact.js";
import type { RuntimeTraceEvent } from "./types.js";

export class JsonlEventStore implements EventStore {
  readonly filePath: string;
  #pending: Promise<void> = Promise.resolve();
  #closed = false;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  append(event: RuntimeTraceEvent): Promise<void> {
    if (this.#closed) {
      return Promise.reject(new RuntimeError("TRACE_WRITE_FAILED", "Trace store is closed"));
    }
    const safe = sanitizeTraceValue(event);
    const line = `${JSON.stringify(safe)}\n`;
    const write = this.#pending.then(async () => {
      await mkdir(dirname(this.filePath), { recursive: true });
      await appendFile(this.filePath, line, { encoding: "utf8", mode: 0o600 });
    });
    this.#pending = write.catch(() => undefined);
    return write.catch((error: unknown) => {
      throw new RuntimeError("TRACE_WRITE_FAILED", "Failed to append runtime trace", {
        cause: error,
      });
    });
  }

  async close(): Promise<void> {
    this.#closed = true;
    await this.#pending;
  }
}
