import { describe, expect, it } from "vitest";
import {
  assertExactToolAllowlist,
  CODING_TOOL_NAMES,
  getToolDenialReason,
} from "../extensions/tool-policy.js";

describe("tool policy", () => {
  it("allows approved delegation tools for a delegating agent", () => {
    const allowed = new Set(["delegate_parallel"]);
    expect(getToolDenialReason("delegate_parallel", allowed, true)).toBeUndefined();
  });

  it("blocks denied and built-in coding tools in the interception guard", () => {
    const allowed = new Set(["safe_tool", "bash"]);
    expect(getToolDenialReason("unknown", allowed, true)).toMatch(/TOOL_NOT_ALLOWED/);
    expect(getToolDenialReason("bash", allowed, true)).toMatch(/TOOL_NOT_ALLOWED/);
    expect(getToolDenialReason("delegate_parallel", new Set(["delegate_parallel"]), false)).toMatch(
      /TOOL_NOT_ALLOWED/,
    );
  });

  it("tracks every Pi coding tool as forbidden", () => {
    expect([...CODING_TOOL_NAMES].sort()).toEqual(
      ["bash", "edit", "find", "grep", "ls", "read", "write"],
    );
  });

  it("fails fast when active tools differ from the explicit allowlist", () => {
    expect(() => assertExactToolAllowlist(["safe", "bash"], new Set(["safe"]))).toThrow(
      /unexpected: bash/,
    );
    expect(() => assertExactToolAllowlist(["safe"], new Set(["safe"]))).not.toThrow();
  });
});
