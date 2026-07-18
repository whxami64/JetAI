import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { RuntimeError } from "../errors.js";
import type { AgentDefinition } from "../agents/types.js";
import type { RuntimeConfig } from "../config/types.js";

export type ResolvedPiModel = NonNullable<ReturnType<ModelRuntime["getModel"]>>;

export function resolvePiModel(
  runtime: ModelRuntime,
  config: RuntimeConfig,
  agent: AgentDefinition,
): ResolvedPiModel {
  const provider = agent.model?.provider ?? config.model.provider;
  const modelId = agent.model?.model ?? config.model.model;
  if (provider === undefined || modelId === undefined) {
    throw new RuntimeError(
      "MODEL_NOT_CONFIGURED",
      "PI_PROVIDER and PI_MODEL are required for a live agent run",
    );
  }
  if (runtime.getProvider(provider) === undefined) {
    throw new RuntimeError("CONFIG_INVALID", `Unknown Pi provider: ${provider}`);
  }
  const model = runtime.getModel(provider, modelId);
  if (model === undefined) {
    throw new RuntimeError("MODEL_NOT_CONFIGURED", `Unknown Pi model: ${provider}/${modelId}`);
  }
  if (!runtime.hasConfiguredAuth(provider)) {
    throw new RuntimeError(
      "MODEL_AUTH_MISSING",
      `No credentials are configured for provider ${provider}`,
    );
  }
  return model;
}
