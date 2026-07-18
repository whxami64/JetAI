# JetAI — Journal Entry Testing Agent

JetAI is an AI audit agent for **journal entry testing (JET)** on accounting exports (GDPdU ledgers, workbooks, and working papers). You upload a dataset; a supervisor agent profiles the files, builds a DuckDB database, runs fraud/control checks, verifies findings, and produces a report. You can then browse evidence and ask follow-up questions in a chat UI.

This guide is for anyone who has never run the project before.

---

## What you need

| Requirement | Notes |
|---|---|
| **Python 3.11+** | 3.12 recommended |
| **[uv](https://docs.astral.sh/uv/)** | Fast Python package manager |
| **OpenAI API key** | Required — the agents call the LLM at runtime |
| **A dataset** | Folder or ZIP of ledgers/tables/documents (sample included) |

Optional: Docker / VS Code Dev Containers if you prefer not to install Python locally (see [Dev container](#dev-container-optional)).

---

## Quick start (web UI)

### 1. Clone and enter the repo

```bash
cd JetAI   # or: git clone <repo-url> && cd JetAI
```

### 2. Install dependencies

```bash
uv sync
source .venv/bin/activate
```

On Windows (PowerShell):

```powershell
uv sync
.venv\Scripts\Activate.ps1
```

### 3. Configure your API key

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
OPENAI_API_KEY=sk-...your-key...
```

Optional overrides:

```env
# Default model if unset: gpt-5.6-sol
OPENAI_MODEL=gpt-4.1
```

### 4. Launch the frontend

```bash
jetai ui
```

Then open **http://127.0.0.1:7860** in your browser.

Useful flags:

```bash
jetai ui --host 0.0.0.0 --port 7860   # listen on all interfaces
jetai ui --share                        # temporary public Gradio link
```

---

## Using the UI to review a dataset

The Gradio app has three tabs.

### Tab 1 — Upload & Run

1. **Prepare a ZIP** of your audit dataset (see [Dataset format](#dataset-format) below).
2. Drop the ZIP into **Audit dataset (ZIP)**.
3. Click **Run audit**.
4. Watch live progress:
   - Stage checklist (preprocess → profile → context → build → checks → verify)
   - **Agent activity** log (tool calls / LLM steps from `traces.jsonl`)

The run can take several minutes (many LLM calls). Only one audit runs at a time.

**Without re-running the agent:** pick an existing directory under `runs/` from the dropdown, click **Load run**, and jump straight to the report (no API cost).

### Tab 2 — Report

After a successful run (or after loading an existing one):

- Short **summary** of confirmed findings
- Table of findings (check, category, entities, amount, confidence)
- Linked detail with source-file references
- Full `report.md`
- **Evidence browser**: pick a finding → pick an evidence SQL statement → **Show offending rows** (replays against the run’s DuckDB)

### Tab 3 — Ask the auditor

Chat with a Q&A agent that has access to that run’s artifacts and traces. Examples:

- “Why was vendor 209101 flagged?”
- “Which check agents ran and what did they find?”
- “Show me the split-payment logic in plain language.”

---

## Dataset format

The agent expects a **directory tree** of accounting exports, for example:

```text
my-dataset/
├── Sachkonten/          # general ledger (GDPdU .txt + index.xml)
├── Kreditoren/          # AP / vendors
├── Debitoren/           # AR / customers
├── AV/                  # fixed assets
└── Begleitdokumente/    # working papers: csv, xlsx, docx, pdf
```

Supported inputs:

| Kind | Extensions |
|---|---|
| GDPdU ledgers | `.txt` (+ `index.xml` / `.dtd` descriptors) |
| Tables | `.csv`, `.xlsx`, `.xls` |
| Documents | `.docx`, `.pdf` |

**ZIP tips for the UI:**

- Zip the dataset folder (or a parent that contains a single dataset folder).
- Include at least one ledger `.txt` or table file under the tree.
- Unsafe ZIP paths (`..`, absolute paths) are rejected.
- On upload, files are extracted under `uploads/<timestamp>/` and may be converted in place (originals archived to `stale/`).

### Sample dataset (included)

A synthetic training set ships with the repo:

```text
data/Uebungsdaten Muster Verpackungen/
```

To review it in the UI, zip it first:

```bash
cd data
zip -r ../sample-dataset.zip "Uebungsdaten Muster Verpackungen"
cd ..
jetai ui
# then upload sample-dataset.zip in the browser
```

Or run the full audit from the CLI without zipping (see below).

> The sample is 100% synthetic (no real names, IBANs, or tax IDs).

---

## CLI (no browser)

Same agent pipeline as the UI, useful for scripting or debugging.

```bash
# Full end-to-end audit (preprocess + supervisor + report)
jetai audit "data/Uebungsdaten Muster Verpackungen"

# Inspect what the agent will see
jetai inventory data

# Convert GDPdU txt / xlsx / docx / pdf only
jetai preprocess data

# Later stages reuse the latest runs/<timestamp>/ (or pass --run)
jetai profile data
jetai context data
jetai build-db data
jetai check --all
jetai verify
jetai trace
jetai eval
```

Artifacts land in:

```text
runs/<UTC-timestamp>/
├── profile.json
├── audit_context.json
├── audit.duckdb
├── build_report.json
├── findings/*.json
├── report.json
├── report.md
└── traces.jsonl
```

---

## What the agent does (pipeline)

| Stage | Purpose |
|---|---|
| **Preprocess** | GDPdU `.txt` → CSV (headers from `index.xml`); xlsx/xls → CSV; docx/pdf → Markdown |
| **Profile** | Survey every file (shape, columns) + LLM annotations → `profile.json` |
| **Context** | Extract materiality, thresholds, four-eyes rules from working papers → `audit_context.json` |
| **Build** | Map sources into canonical DuckDB views → `audit.duckdb` |
| **Checks** | Specialist agents (e.g. three-way match, cut-off, account classification, split payments, four-eyes) |
| **Verify** | Cross-check findings, drop weak ones, write the final report |

Typical risk themes on the sample set: fake vendors / no goods receipt, repairs capitalised as assets, year-end cut-off, split payments under approval limits, four-eyes / segregation of duties breaches.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Missing OpenAI configuration` | Copy `.env.example` → `.env`, set `OPENAI_API_KEY`, restart `jetai ui` |
| `No ledger or table exports found` | ZIP/path has no `.txt` / `.csv` / `.xlsx` under it; check nesting |
| `An audit run is already in progress` | Wait for the current run to finish (one at a time) |
| Port 7860 in use | `jetai ui --port 7861` |
| `command not found: jetai` | Activate the venv (`source .venv/bin/activate`) after `uv sync` |
| Load existing run fails | Enter the dataset root manually (e.g. `uploads/.../dataset`) if traces cannot recover it |
| Very slow / expensive run | Expected — many sequential LLM + tool steps; use **Load run** to re-open finished results free of charge |

---

## Dev container (optional)

If you use VS Code / Cursor with Dev Containers:

1. Open the folder in the container (uses `.devcontainer/`).
2. Dependencies install via `uv sync --extra dev` on create.
3. Create `.env` with `OPENAI_API_KEY` as above.
4. Run `jetai ui` in the integrated terminal and open the forwarded port **7860**.

---

## Development extras

```bash
uv sync --extra dev          # pytest, ruff, mypy, pre-commit
pytest                       # unit tests (no live API)
pytest -m integration        # hits the OpenAI API
pre-commit install
```

---

## Project layout (high level)

```text
src/jetai/
  agents/     # supervisor, specialists, tools, tracing
  web/        # Gradio UI (upload, progress, report, Q&A)
  cli.py      # jetai command
  dataset.py  # dataset discovery
  preprocess.py
data/         # sample GDPdU + working papers
runs/         # audit outputs (created at runtime)
uploads/      # UI ZIP extractions (created at runtime)
eval/         # optional ground truth for jetai eval
```

---

## License

Proprietary — see project authors / organisers for redistribution terms.
