const SECRET_KEY = /(api[-_]?key|authorization|password|secret|token|credential|cookie)/i;
const HIDDEN_KEY = /(reasoning|chain[-_]?of[-_]?thought|thinking)/i;

export interface SanitizeOptions {
  maxStringLength?: number;
}

export function sanitizeTraceValue(
  value: unknown,
  options: SanitizeOptions = {},
  seen = new WeakSet(),
): unknown {
  const maxStringLength = options.maxStringLength ?? 2_000;
  if (typeof value === "string") {
    return value.length <= maxStringLength ? value : `${value.slice(0, maxStringLength)}...[truncated]`;
  }
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return "[circular]";
  seen.add(value);
  if (Array.isArray(value)) {
    return value.slice(0, 100).map((item) => sanitizeTraceValue(item, options, seen));
  }
  const output: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (SECRET_KEY.test(key)) output[key] = "[redacted]";
    else if (HIDDEN_KEY.test(key)) output[key] = "[omitted]";
    else output[key] = sanitizeTraceValue(item, options, seen);
  }
  return output;
}
