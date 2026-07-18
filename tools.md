# jetai CLI

```bash
uv sync && source .venv/bin/activate
cp .env.example .env   # set OPENAI_API_KEY
```

## Commands

```bash
jetai inventory [PATH]        # list source documents, grouped by kind (default PATH: data)
jetai preprocess [PATH]       # GDPdU txt -> csv (header from index.xml), xlsx/xls -> csv,
                              # docx/pdf -> md; originals archived to stale/; idempotent
jetai audit [PATH]            # full supervisor run: preprocess check, profile, context,
                              # build, checks, verify; prints report + runs/<ts>/ path
jetai profile [PATH] [--run DIR]   # survey every file + LLM annotations -> profile.json
jetai context [PATH] [--run DIR]   # thresholds/rules from working papers -> audit_context.json
jetai build-db [PATH] [--run DIR]  # canonical DuckDB views -> audit.duckdb + build_report.json
jetai check <name>|--all [--run DIR]  # three_way_match | cutoff | account_classification
                                      # | split_payments | four_eyes -> findings/<name>.json
jetai verify [--run DIR]      # verifier agent -> report.json + report.md
jetai eval [--run DIR] [--truth FILE]  # score report vs eval/ground_truth.json
jetai trace [--run DIR] [--full]       # per-agent LLM/tool/token summary of traces.jsonl
jetai ui [--host H] [--port P] [--share]  # Gradio web UI: upload a dataset ZIP, watch the
                                          # audit live, browse the report (source-file links,
                                          # evidence SQL replay), then chat with a Q&A agent
                                          # over the run's traces and artifacts
```

`--run` defaults to the latest directory under `runs/`; stages read the earlier
stages' artifacts from it, so one stage can be iterated without rerunning the rest.

## Traces

Each run's `traces.jsonl` has one JSON line per LLM/tool event with an `agent` field:

```bash
jq -r 'select(.event=="tool_start") | "\(.agent) \(.tool) \(.input)"' runs/*/traces.jsonl
jq 'select(.event=="llm_end") | .usage' runs/*/traces.jsonl
```
