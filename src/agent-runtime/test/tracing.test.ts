import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { afterEach, describe, expect, it } from "vitest";
import { JsonlEventStore } from "../tracing/jsonl-event-store.js";
import type { RuntimeTraceEvent } from "../tracing/types.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("JsonlEventStore", () => {
  it("serializes concurrent appends and redacts sensitive or hidden fields", async () => {
    const directory = await mkdtemp(join(tmpdir(), "jetai-trace-"));
    directories.push(directory);
    const path = join(directory, "trace.jsonl");
    const store = new JsonlEventStore(path);
    const event = (index: number): RuntimeTraceEvent => ({
      eventId: String(index),
      eventType: "tool.requested",
      timestamp: new Date().toISOString(),
      rootRunId: "root",
      runId: "child",
      parentRunId: "root",
      agentId: "specialist",
      depth: 1,
      data: { apiKey: "secret", reasoning: "hidden", index },
    });
    await Promise.all(Array.from({ length: 20 }, (_, index) => store.append(event(index))));
    await store.close();
    const lines = (await readFile(path, "utf8")).trim().split("\n");
    expect(lines).toHaveLength(20);
    const parsed = lines.map((line): RuntimeTraceEvent => JSON.parse(line) as RuntimeTraceEvent);
    expect(parsed[0]?.data).toMatchObject({ apiKey: "[redacted]", reasoning: "[omitted]" });
    expect(new Set(parsed.map((item) => item.eventId)).size).toBe(20);
  });
});
