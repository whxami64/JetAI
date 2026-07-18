import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  type InlineExtension,
  type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeConfig } from "../config/types.js";
import type { RuntimeContext } from "./runtime-context.js";
import { resolvePiModel } from "./model-registry.js";
import { assertExactToolAllowlist } from "../extensions/tool-policy.js";

export interface CreateSessionOptions {
  agent: AgentDefinition;
  runtimeContext: RuntimeContext;
  tools: ToolDefinition[];
  extensions: InlineExtension[];
  persistent: boolean;
}

export interface RuntimeSession {
  readonly activeTools: string[];
  run(prompt: string, signal?: AbortSignal): Promise<void>;
  stats(): {
    turns: number;
    toolCalls: number;
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
    estimatedCost: number;
  };
  close(): Promise<void>;
}

export interface SessionFactory {
  create(options: CreateSessionOptions): Promise<RuntimeSession>;
}

export class PiSessionFactory implements SessionFactory {
  readonly #config: RuntimeConfig;
  #modelRuntime: ModelRuntime | undefined;

  constructor(config: RuntimeConfig) {
    this.#config = config;
  }

  async create(options: CreateSessionOptions): Promise<RuntimeSession> {
    this.#modelRuntime ??= await ModelRuntime.create({ allowModelNetwork: false });
    const model = resolvePiModel(this.#modelRuntime, this.#config, options.agent);
    const settings = SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: this.#config.limits.maxRetries > 0, maxRetries: this.#config.limits.maxRetries },
    });
    const agentDir = resolve(this.#config.cwd, ".runtime/pi");
    const loader = new DefaultResourceLoader({
      cwd: this.#config.cwd,
      agentDir,
      settingsManager: settings,
      extensionFactories: options.extensions,
      noExtensions: true,
      noSkills: true,
      noPromptTemplates: true,
      noThemes: true,
      noContextFiles: true,
      systemPrompt: options.agent.systemPrompt,
      appendSystemPrompt: [],
    });
    await loader.reload();
    if (options.persistent) await mkdir(this.#config.sessionDir, { recursive: true });
    const sessionManager = options.persistent
      ? SessionManager.create(this.#config.cwd, this.#config.sessionDir, {
          id: options.runtimeContext.runId,
        })
      : SessionManager.inMemory(this.#config.cwd, { id: options.runtimeContext.runId });
    const allowed = new Set(options.agent.allowedTools);
    const { session } = await createAgentSession({
      cwd: this.#config.cwd,
      agentDir,
      modelRuntime: this.#modelRuntime,
      model,
      thinkingLevel: options.agent.model?.thinkingLevel ?? this.#config.model.thinkingLevel,
      tools: [...allowed],
      customTools: options.tools,
      resourceLoader: loader,
      sessionManager,
      settingsManager: settings,
      sessionStartEvent: { type: "session_start", reason: "startup" },
    });
    try {
      await session.bindExtensions({ mode: "print" });
      assertExactToolAllowlist(session.getActiveToolNames(), allowed);
    } catch (error) {
      await session.abort();
      session.dispose();
      throw error;
    }
    let closed = false;
    return {
      activeTools: session.getActiveToolNames(),
      async run(prompt, signal) {
        signal?.throwIfAborted();
        const abort = () => void session.abort();
        signal?.addEventListener("abort", abort, { once: true });
        try {
          await session.prompt(prompt, {
            expandPromptTemplates: false,
            source: "extension",
          });
        } finally {
          signal?.removeEventListener("abort", abort);
        }
      },
      stats() {
        const stats = session.getSessionStats();
        return {
          turns: stats.assistantMessages,
          toolCalls: stats.toolCalls,
          inputTokens: stats.tokens.input,
          outputTokens: stats.tokens.output,
          totalTokens: stats.tokens.total,
          estimatedCost: stats.cost,
        };
      },
      async close() {
        if (closed) return;
        closed = true;
        let abortError: unknown;
        try {
          await session.abort();
        } catch (error) {
          abortError = error;
        }
        try {
          await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" });
        } finally {
          session.dispose();
        }
        if (abortError instanceof Error) throw abortError;
        if (abortError !== undefined) {
          throw new Error("Failed to abort Pi session during cleanup", { cause: abortError });
        }
      },
    };
  }
}
