# 3-Wege-Check: join agent + check agent (LangGraph + DuckDB + OpenAI)

## Context

`approach.md` calls for a 3-way match (PO/Invoice/Payment, with Goods Receipt
bracketed as a 4th check) over the GDPdU audit export in `data/`. Investigation
of the actual files shows **no purchase-order data exists anywhere in the
dataset** — the only vendor-side sources are the AP sub-ledger
(`Kreditoren/Lieferantenbuchungen.txt`, which holds both invoice and payment
rows) and the goods-receipt list
(`Begleitdokumente/Wareneingangsliste_2025.csv`). So the match we can actually
run, and the one `solution.md` (the answer key for this exercise) confirms
catches the headline fraud (F1, vendor 209101 "Ratio Consulting GmbH"), is
**Invoice ↔ Payment ↔ Goods Receipt**.

Decisions made with the user before this plan:
- Build two runtime agents, not a deterministic pipeline: a **join agent**
  that produces a persisted `.duckdb` file, and a **check agent** that queries
  it and reports findings via a structured tool call.
- Also build the broader normalized journal union (all four sub-ledgers in one
  common-schema table), not just the narrow reconciliation table — useful for
  the other checks in `approach.md` later.
- Orchestration via **LangGraph** (`langgraph.prebuilt.create_react_agent`),
  even though today's pipeline is linear — chosen for consistency with the
  rest of the planned audit-agent suite.
- Models are **OpenAI** (not Anthropic, despite the `anthropic` package
  already in `pyproject.toml` — that dependency is unused today and is left
  alone). Default model: `gpt-5`, configurable via `.env`.
- Guardrail: the check agent's logic must be generic ("any invoice with a
  payment but no matching goods receipt"), never hardcoded to vendor 209101 or
  other `solution.md` specifics — otherwise it's replaying the answer key, not
  detecting fraud, and the dataset is explicitly documented as regenerable.

## Architecture

```
jetai preprocess data        (extended, deterministic)
        │
        ▼
jetai join data               ── Join Agent (LangGraph ReAct, OpenAI + execute_sql tool)
        │                         writes <dataset root>/audit.duckdb
        ▼
jetai check-3way               ── Check Agent (LangGraph ReAct, OpenAI + execute_sql
        │                         + report_findings tools, read-only)
        ▼
   findings (rich table)

jetai three-way-check data    convenience wrapper: join, then check
```

## 1. Deterministic preprocessing extension (not an agent)

The GDPdU ledger `.txt` files (`Sachkonten/*.txt`, `Kreditoren/*.txt`,
`Debitoren/*.txt`, `AV/*.txt`) are headerless, cp1252-encoded, `;`-delimited.
Column names live in each directory's sibling `index.xml`
(`<Table><URL>Sachkontobuchungen.txt</URL>...<VariableColumn><Name>...`).
This is 100% mechanical — no agent judgment needed — so it belongs in
`preprocess.py`, matching `approach.md`'s own preprocessing checklist item
("Trennzeichen vereinheitlichen").

Add to `src/jetai/preprocess.py`:
- `_parse_ledger_columns(index_xml: Path, table_url: str) -> list[str]` — parse
  the DTD-described XML (stdlib `xml.etree.ElementTree`) and return the
  ordered `VariableColumn/Name` list for the `<Table>` whose `<URL>` matches.
- `_convert_ledger(txt_path: Path, columns: list[str]) -> Path` — read as
  `cp1252`, write a `;`-separated `.csv` with the header row prepended, UTF-8
  encoded. Leave values as-is (decimal comma, `DD.MM.YYYY` dates) — typing is
  the join agent's job, not preprocessing's.
- Wire into `preprocess_dataset`: iterate `inventory.ledgers`, resolve each
  `.txt`'s sibling `index.xml`, convert, and archive the original `.txt` via
  the existing `_archive()` helper — same idempotent pattern already used for
  xlsx/docx/pdf (`STALE_DIRNAME`).

No changes needed to `dataset.py`: `_has_ledger` already scans unfiltered by
`stale/`, so `find_dataset_root` keeps working after ledgers are archived.

## 2. New package: `src/jetai/agents/`

### `agents/tools.py`
- `make_execute_sql_tool(conn: duckdb.DuckDBPyConnection) -> BaseTool` — a
  `@tool`-decorated closure over an open connection. Runs the query, returns
  results as a capped markdown-ish text table (hard cap ~200 rows — the GL
  table alone is 20k rows; the agent must aggregate, not dump raw rows).
  Catches `duckdb.Error` and returns the message as text so the agent can
  self-correct instead of crashing the loop.
- `make_list_source_files_tool(dataset_root: Path) -> BaseTool` — thin wrapper
  over the existing `jetai.dataset.build_inventory`, returns relative paths
  grouped by kind. No args (root is bound via closure), so the agent can
  discover what's available after preprocessing without the file layout being
  hardcoded into the prompt.

### `agents/config.py`
- `AgentSettings(BaseSettings)` (pydantic-settings, `env_file=".env"`):
  `openai_api_key: str`, `openai_model: str = "gpt-5"`. First real use of the
  `pydantic-settings`/`python-dotenv` deps that are already declared but
  unused.
- Update `.env.example` to add `OPENAI_API_KEY=` and
  `# OPENAI_MODEL=gpt-5` alongside the existing (unused) Anthropic entries —
  leave those as-is, out of scope to remove.

### `agents/join_agent.py`
- System prompt covers: the preprocessed source CSVs and their key columns
  (now headered/UTF-8 after step 1), the decimal-comma/date-format quirk to
  cast in SQL, and the target schema below. Built via
  `langgraph.prebuilt.create_react_agent(model=ChatOpenAI(...), tools=[execute_sql, list_source_files])`.
- `run_join_agent(dataset_root: Path, out_path: Path) -> JoinResult` — opens
  `duckdb.connect(str(out_path))` read-write, runs the agent with a
  `recursion_limit` safeguard (e.g. 40), and returns a small result object
  (tables created + row counts, read back from `duckdb_tables()`/`COUNT(*)`
  after the run — verification independent of what the agent claims it did).

Target tables (agent builds these via `CREATE TABLE ... AS SELECT`, exact SQL
is the agent's call, not hardcoded by us):
- **Typed pass-throughs**: `lieferanten`, `kunden`, `sachkonten`, `anlagen`
  (master data), `vendor_postings`, `customer_postings`, `gl_postings`,
  `asset_postings`, `goods_receipts`, `goods_issues`, `sales_invoices`,
  `late_vendor_invoices` (the Jan-2026 cutoff file), `master_data_changes`,
  `approval_log` — each with `,`→`.` amount casts and `strptime` date parsing
  applied.
- **`journal`** — `UNION ALL` of `vendor_postings`/`customer_postings`/
  `gl_postings`/`asset_postings` mapped to a common schema
  (`source_ledger, account, counter_account, posting_date, document_date,
  document_number, text, amount, currency, user, entry_datetime`), NULL where
  a sub-ledger has no equivalent column. This is the "mega table."
- **`three_way_match`** — grain = one row per vendor invoice
  (`vendor_account, invoice_number`), LEFT JOIN aggregated payments (sum,
  count, last date) and LEFT JOIN `goods_receipts`. Purely factual (amounts,
  dates, presence via NULL) — no "is this suspicious" judgment here, that's
  the check agent's job, keeping the join/check split clean per the user's
  original framing.

### `agents/check_agent.py`
- `Finding(BaseModel)`: `invoice_number`, `vendor_account`, `vendor_name`,
  `category: Literal["invoice_without_goods_receipt",
  "goods_receipt_without_invoice", "amount_mismatch", "unusual_timing",
  "other"]`, `amount_eur`, `evidence: str` (must cite the query/rows that back
  it up), `confidence: Literal["low","medium","high"]`.
  `FindingsReport(BaseModel)`: `findings: list[Finding]`, `summary: str`.
- `report_findings` tool: pydantic-args tool that validates + stashes the
  `FindingsReport` in a closure variable and returns `"recorded N findings"`
  to the model. The ReAct loop then naturally ends when the model stops
  calling tools; `run_check_agent` reads the stashed report back — avoids
  custom graph surgery to force-terminate on a specific tool call.
- System prompt is deliberately generic: describes what a clean 3-way match
  looks like (invoice needs a payment and a goods receipt; amounts should
  reconcile; timing should be sane) and instructs the agent to query
  `three_way_match`/`journal`/master tables and investigate anomalies itself
  — no vendor numbers or `solution.md` facts in the prompt.
- `run_check_agent(db_path: Path) -> FindingsReport` — opens
  `duckdb.connect(str(db_path), read_only=True)` (defense against the check
  agent mutating the join agent's output), same `execute_sql` tool bound to
  this connection, plus `report_findings`.

## 3. CLI wiring (`src/jetai/cli.py`)

- `jetai join [PATH] [--out FILE]` (default out: `<dataset root>/audit.duckdb`)
  — runs the join agent, prints a rich table of tables created + row counts.
- `jetai check-3way [--db FILE]` — runs the check agent, prints findings as a
  rich table.
- `jetai three-way-check [PATH]` — convenience wrapper calling both in
  sequence. Kept separate from the two above so each agent can be iterated on
  (prompt tuning) independently without re-running the other.

## 4. Dependencies (`pyproject.toml`)

Add to `[project.dependencies]`: `duckdb>=1.5`, `langgraph>=1.2`,
`langchain-openai>=1.3`, `langchain-core>=1.4` (used directly for the `@tool`
decorator). Confirmed all four install cleanly on the pinned Python 3.12.

## 5. Tests

- `tests/test_preprocess.py` (extend) — fixture with a tiny synthetic
  `.txt` + `index.xml` pair mirroring the real GDPdU shape; assert the output
  `.csv` has the correct header row, UTF-8 content (umlaut round-trips), and
  the original is archived to `stale/`.
- `tests/test_agent_tools.py` (new) — pure unit tests of `execute_sql` and
  `list_source_files` against a tmp DuckDB/dataset fixture. No LLM calls.
- `tests/test_join_agent.py` / `tests/test_check_agent.py` (new) — marked
  with a new `integration` pytest marker (register it in
  `[tool.pytest.ini_options]`), `skipif` when `OPENAI_API_KEY` is unset. Runs
  the real agents end-to-end against the repo's `data/` fixture and asserts:
  join produces the expected tables with sane row counts; check surfaces a
  finding referencing vendor `209101` by category
  `invoice_without_goods_receipt` (validates the *generic* logic reaches the
  known answer, without the prompt ever naming that vendor) and does **not**
  flag decoy `209112` (Vega Werkstoffe, the honest twin in `solution.md`).
- All new modules must satisfy `mypy --strict` (already enforced project-wide)
  and `ruff` (E/F/I/UP/B/SIM/W).

## Verification

1. `uv sync` (pulls in the new deps).
2. `cp .env.example .env`, fill in `OPENAI_API_KEY`.
3. `jetai preprocess data` — confirm ledger `.txt` files move to `stale/` and
   headered UTF-8 `.csv` siblings appear.
4. `jetai join data` — inspect `audit.duckdb` (`duckdb` CLI or Python):
   `three_way_match` should have ~2,500 rows (one per vendor invoice);
   vendor `209101`'s five rows should have NULL goods-receipt columns.
5. `jetai check-3way` — confirm vendor `209101` is flagged
   (`invoice_without_goods_receipt`) and `209112` is not.
6. `pytest`, `ruff check .`, `mypy` — should all pass (matches the existing
   pre-commit hooks).
