import type { EventStore } from "../tracing/event-store.js";

export class DelegationBudget {
  #used = 0;

  constructor(readonly maximum: number) {}

  get used(): number {
    return this.#used;
  }

  reserve(count: number): boolean {
    if (count < 0 || this.#used + count > this.maximum) return false;
    this.#used += count;
    return true;
  }
}

export interface RuntimeContext {
  runId: string;
  parentRunId?: string;
  rootRunId: string;
  agentId: string;
  depth: number;
  delegationBudget: DelegationBudget;
  eventStore: EventStore;
  signal?: AbortSignal;
}

export function childRuntimeContext(
  parent: RuntimeContext,
  runId: string,
  agentId: string,
  signal?: AbortSignal,
): RuntimeContext {
  return {
    runId,
    parentRunId: parent.runId,
    rootRunId: parent.rootRunId,
    agentId,
    depth: parent.depth + 1,
    delegationBudget: parent.delegationBudget,
    eventStore: parent.eventStore,
    ...(signal === undefined ? {} : { signal }),
  };
}
