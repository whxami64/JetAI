import { RuntimeError } from "../errors.js";

interface Waiter {
  resolve: () => void;
  reject: (error: RuntimeError) => void;
  signal?: AbortSignal;
  onAbort?: () => void;
}

export class Scheduler {
  readonly #maximum: number;
  #active = 0;
  readonly #waiting: Waiter[] = [];

  constructor(maximum: number) {
    if (!Number.isSafeInteger(maximum) || maximum < 1) {
      throw new RuntimeError("CONFIG_INVALID", "Scheduler concurrency must be at least one");
    }
    this.#maximum = maximum;
  }

  get active(): number {
    return this.#active;
  }

  async run<T>(
    task: (signal: AbortSignal) => Promise<T>,
    options: { signal?: AbortSignal; timeoutMs: number },
  ): Promise<T> {
    await this.#acquire(options.signal);
    const timeout = new AbortController();
    const combined = options.signal === undefined
      ? AbortSignal.any([timeout.signal])
      : AbortSignal.any([options.signal, timeout.signal]);
    const timer = setTimeout(() => timeout.abort(new RuntimeError("SUBAGENT_TIMEOUT", "Subagent timed out")), options.timeoutMs);
    timer.unref();
    try {
      const value = await task(combined);
      if (combined.aborted) throw this.#abortReason(options.signal, timeout.signal);
      return value;
    } catch (error) {
      if (combined.aborted) throw this.#abortReason(options.signal, timeout.signal);
      throw error;
    } finally {
      clearTimeout(timer);
      this.#release();
    }
  }

  #abortReason(parent: AbortSignal | undefined, timeout: AbortSignal): RuntimeError {
    if (parent?.aborted === true) {
      return new RuntimeError("RUN_ABORTED", "Run was aborted", { cause: parent.reason });
    }
    return new RuntimeError("SUBAGENT_TIMEOUT", "Subagent timed out", { cause: timeout.reason });
  }

  async #acquire(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted === true) {
      throw new RuntimeError("RUN_ABORTED", "Run was aborted", { cause: signal.reason });
    }
    if (this.#active < this.#maximum) {
      this.#active += 1;
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const waiter: Waiter = {
        resolve,
        reject,
        ...(signal === undefined ? {} : { signal }),
      };
      if (signal !== undefined) {
        waiter.onAbort = () => {
          const index = this.#waiting.indexOf(waiter);
          if (index >= 0) this.#waiting.splice(index, 1);
          reject(new RuntimeError("RUN_ABORTED", "Run was aborted", { cause: signal.reason }));
        };
        signal.addEventListener("abort", waiter.onAbort, { once: true });
      }
      this.#waiting.push(waiter);
    });
  }

  #release(): void {
    const waiter = this.#waiting.shift();
    if (waiter === undefined) {
      this.#active -= 1;
      return;
    }
    if (waiter.signal !== undefined && waiter.onAbort !== undefined) {
      waiter.signal.removeEventListener("abort", waiter.onAbort);
    }
    waiter.resolve();
  }
}
