import "dotenv/config";
import { createAgentRuntime, loadRuntimeConfig } from "../index.js";

async function main(): Promise<void> {
  const config = loadRuntimeConfig();
  const runtime = await createAgentRuntime({ config });
  try {
    const result = await runtime.run({
      objective: [
        "Analyze this fictional product incident using only the supplied facts.",
        "A batch job failed shortly after a configuration change.",
        "An initial observer suspects the change, but no rollback test has been performed.",
        "Return supported findings and unresolved questions.",
      ].join(" "),
      context: { caseId: "runtime-smoke-001", fictional: true },
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    process.stdout.write(`Trace: ${runtime.tracePath(result.runId)}\n`);
    if (result.status !== "completed") process.exitCode = 1;
  } finally {
    await runtime.close();
  }
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "Unknown demo failure";
  process.stderr.write(`Agent demo failed: ${message}\n`);
  process.exitCode = 1;
});
