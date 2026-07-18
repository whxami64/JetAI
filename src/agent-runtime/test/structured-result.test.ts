import { describe, expect, it } from "vitest";
import { createStructuredResultCapture } from "../extensions/structured-result.js";
import { SupervisorSubmissionSchema } from "../schemas/run-result.js";
import { testContext } from "./fixtures.js";

describe("structured result capture", () => {
  it("accepts one valid submission and rejects a conflicting second submission", async () => {
    const capture = createStructuredResultCapture({
      name: "submit",
      label: "Submit",
      description: "Submit result",
      schema: SupervisorSubmissionSchema,
      runtimeContext: testContext(),
    });
    const payload = { summary: "ok", findings: [], unresolvedQuestions: [] };
    await capture.tool.execute("one", payload, undefined, undefined, {} as never);
    expect(capture.get()).toEqual(payload);
    await expect(
      capture.tool.execute("two", payload, undefined, undefined, {} as never),
    ).rejects.toMatchObject({ code: "RESULT_ALREADY_SUBMITTED" });
  });
});
