# Implementation plan: JET audit agent suite (LangGraph + DuckDB + OpenAI)

Supersedes the previous 3-way-check-only plan; now covers the full agent suite
from `approach.md` with all user feedback incorporated.

## Decisions (agreed with the user)

- **Orchestration: LLM supervisor agent.** A `create_agent` supervisor invokes
  the specialist agents as tools and decides the order dynamically. To avoid
  the known supervisor failure mode (findings get paraphrased and degraded at
  each handoff), every subagent writes its full output as a **structured
  artifact on disk** and returns only a compact summary + artifact path to the
  supervisor. The verifier reads the findings files directly — the
  supervisor never retypes evidence.
- **Observability: local JSONL traces only.** No external service. Every LLM
  call and tool call of every agent is appended to `traces.jsonl` in the run
  directory via a custom callback handler.
- **Models: OpenAI** (`gpt-5` default, override via `OPENAI_MODEL` in `.env`).
  The unused `anthropic` dependency is **deleted** from `pyproject.toml`, and
  its `.env.example` entries are removed.
- **API: `langchain.agents.create_agent`** (langchain 1.x), not
  `langgraph.prebuilt.create_react_agent` — the latter is deprecated in
  langgraph 1.0 and removed in 2.0. `create_agent` runs on the langgraph
  runtime and supports `response_format=<pydantic model>` for enforced
  structured final answers (verified: langchain 1.x, langgraph 1.2.9,
  langchain-openai 1.3.5, duckdb 1.5.4 all current on PyPI).
- **Generalization is a hard requirement.** The suite must work on a dataset
  from a different accounting software: different file names, different column
  names, different column counts. Verified empirically on our own data that
  this variance is real even within one export: the GDPdU tables have 7–24
  columns with names only in `index.xml`, and the xlsx workbooks
  (Berechtigungsauswertung, OP-Listen, Saldenliste) hide their real header
  under 1–2 title rows. Consequences:
  - No file names, column names, vendor numbers, or any `solution.md` facts
    in agent prompts or code paths (except the deterministic GDPdU
    `index.xml` parser, which is a published standard).
  - All schema knowledge is discovered at runtime (profiling agent) and
    absorbed at one choke point (canonical DuckDB views). Check agents only
    ever see the canonical schema.
  - Agents inspect schemas/heads before querying — never load whole files
    into context.

## Architecture

```
                        ┌──────────────────────────────────┐
                        │  Supervisor agent (create_agent) │
                        │  tools = the boxes below         │
                        └──────────────────────────────────┘
   deterministic code            agents-as-tools                 artifacts (run dir)
┌─────────────────────┐   ┌───────────────────────────┐
│ jetai preprocess    │   │ profile_dataset           │──────▶ profile.json
│ (extended, no LLM)  │   │ extract_audit_context     │──────▶ audit_context.json
└─────────────────────┘   │ build_database            │──────▶ audit.duckdb + build_report.json
                          │ run_check(check_name) ×5  │──────▶ findings/<check>.json
                          │ verify_findings           │──────▶ report.json + report.md
                          └───────────────────────────┘
                          every call traced ─────────────────▶ traces.jsonl
```

Each specialist is its own `create_agent` instance invoked **with a fresh,
self-contained brief** (no shared message history — context isolation). The
supervisor's prompt describes the standard audit program (profile → context →
build → checks → verify) but lets it adapt: skip checks whose required
canonical tables are missing, re-invoke `build_database` on failure, rerun a
check with a refinement note.

### Run directory

Every `jetai audit` run creates `runs/<UTC timestamp>/` (git-ignored):
`profile.json`, `audit_context.json`, `audit.duckdb`, `build_report.json`,
`findings/*.json`, `report.json`, `report.md`, `traces.jsonl`. Individual CLI
commands (`jetai profile`, `jetai check …`) accept `--run DIR` to reuse an
existing run dir, so each agent can be iterated on without rerunning the rest.

## Data map & join proposition (investigated)

Empirical survey of the dataset — these keys exist and join (verified against
file heads). The build agent discovers the equivalents at runtime via the
profile; this table documents *our* dataset and seeds the canonical schema:

| Source | Join key(s) | Joins to / enables |
|---|---|---|
| `Kreditoren/Lieferanten.txt` (142 vendors) | vendor account no. | vendor dim: name, VAT-ID, address, group → new-vendor & duplicate-vendor analysis |
| `Debitoren/Kunden.txt` (159) | customer account no. | customer dim |
| `Sachkonten/Sachkonten.txt` (42) | G/L account no. | account dim: name + Bilanz/GuV type → classification check needs account *names* |
| `AV/Anlagen.txt` (196) | asset no., G/L class | asset dim: asset *names* (repair-word scan) |
| `Kreditoren/Lieferantenbuchungen.txt` (2.5k) | vendor, document no., date | AP invoices + payments (3-way match core) |
| `Debitoren/Kundenbuchungen.txt` (3.7k) | customer, invoice no. | AR side |
| `Sachkonten/Sachkontobuchungen.txt` (20k) | account, Erfassungsnummer, journal, user, date | the GL journal; `ERFASSUNGSNUMMER` links to Freigabe-Log |
| `Wareneingangsliste_2025.csv` (858) | RECHNUNGSNUMMER, KREDITOR | goods receipts ↔ AP invoices (3-way match, cut-off "Rechnung offen") |
| `Warenausgangsliste_2025.csv` (2k) | RECHNUNGSNUMMER, DEBITOR | goods issues ↔ AR invoices |
| `Fakturajournal_2025.csv` (2k) | RECHNUNGSNUMMER, DEBITOR | sales invoices, FAKTURA vs LEISTUNGSDATUM |
| `Fakturajournal_Januar_2026_Kreditoren.csv` (8) | KREDITOR, LEISTUNGSDATUM | cut-off: Jan-2026 invoices for 2025 services |
| `Buchungen_Folgeperiode_2026.csv` (60) | DEBITOR, GEGENKONTO | cut-off: next-period postings |
| `Freigabe-Log_Journale_2025.csv` (91) | ERFASSUNGSNUMMER, ERSTELLER/FREIGEBER | four-eyes on journals; user link |
| `Stammdatenaenderungen_2025.csv` (19) | KONTO, GEAENDERT_VON/GENEHMIGT_VON | four-eyes on master data; new-vendor creation events |
| `Berechtigungsauswertung_2025.xlsx` (10 users) | user ID | user dim: rights matrix → segregation-of-duties |
| `OP-Liste_{Kreditoren,Debitoren}_2025.xlsx` | account no. | open items; verifier tie-outs |
| `Saldenliste_2025.xlsx`, `Saldenliste_2024_Vorjahr.xlsx`, `Abstimmung_Nebenbuecher_HB_2025.xlsx` | G/L account no. | trial balances; completeness/reconciliation |
| `Kreditlimitliste_Debitoren_2025.csv` (160) | DEBITOR | customer credit limits |
| `Gesellschafterliste_Beteiligungen.csv` (5) | name (fuzzy) | related-party flags on vendor/customer names |
| `Pruefungsplanung_JET_2025.docx` → `.md` | — | audit context: thresholds, materiality, selection criteria |
| PDFs (Exportprotokoll, IT-Bestätigung, JA-Entwurf) → `.md` | — | context/tie-out only, not joined |

**Canonical schema** (DuckDB views the build agent must produce; names fixed,
sources discovered):

- Dims: `dim_vendor`, `dim_customer`, `dim_account`, `dim_asset`, `dim_user`
- Facts: `vendor_postings`, `customer_postings`, `gl_postings`,
  `asset_postings`, `goods_receipts`, `goods_issues`, `sales_invoices`,
  `late_vendor_invoices`, `next_period_postings`, `approval_log`,
  `master_data_changes`, `open_items_ap`, `open_items_ar`, `trial_balance`
- Derived: `journal` (UNION ALL of the four posting ledgers on a common
  column set: `source_ledger, account, counter_account, posting_date,
  document_date, document_number, text, amount, currency, user_id,
  entry_id`), and `three_way_match` (grain: one row per vendor invoice,
  LEFT JOIN aggregated payments and goods receipts — purely factual, NULLs
  mark absence; judgment belongs to the check agent)

A canonical view may be legitimately absent (e.g. no goods-receipt file in a
different export) — the build report records which views exist, and the
supervisor skips checks whose required views are missing.

## 1. Deterministic preprocessing extension (no LLM)

Extend `src/jetai/preprocess.py` — mechanical, standard-driven, generic:

- `_parse_gdpdu_tables(index_xml: Path) -> dict[str, list[str]]` — parse
  every `<Table>` (stdlib ElementTree): `URL` → ordered `VariableColumn/Name`
  list. **No table names or column counts hardcoded** — works for any GDPdU
  export regardless of what the tables are called.
- `_convert_ledger(txt: Path, columns: list[str]) -> Path` — decode
  (try `utf-8-sig` strict, fall back `cp1252` — both occur in this dataset),
  prepend the header row, write `;`-separated UTF-8 `.csv`. Rows whose field
  count mismatches the descriptor are kept and counted, not dropped. Values
  stay raw (decimal comma, `DD.MM.YYYY`) — typing happens in SQL at build
  time.
- Wire into `preprocess_dataset`: for each directory containing an
  `index.xml`, convert the `.txt` files it describes and archive originals
  via the existing `_archive()`/`stale/` pattern. A `.txt` ledger *without* a
  descriptor is left in place — the profiling agent will flag it (that is the
  generalization path for non-GDPdU software: its CSVs usually ship headers).

No `dataset.py` changes needed (`_has_ledger` scans ignore `stale/` already).

Note on formats: `_convert_spreadsheet` keeps emitting pandas' decimal-point
/ ISO style even though the native files are German-style — that mixture
across files is fine because it is *consistent per file*, and the profiler's
format detector (§3.1) runs on the post-conversion files and records each
file's actual formats for the build agent. Preprocessing itself never
parses dates or numbers.

## 2. New package `src/jetai/agents/`

### `config.py`
`AgentSettings(BaseSettings)` with `env_file=".env"`: `openai_api_key: str`,
`openai_model: str = "gpt-5"`, `runs_dir: Path = Path("runs")`. First real use
of the already-declared `pydantic-settings`/`python-dotenv` deps. Update
`.env.example`: add `OPENAI_API_KEY=`, `# OPENAI_MODEL=gpt-5`; delete the
Anthropic entries.

### `tracing.py`
`JsonlTracer(BaseCallbackHandler)` — appends one JSON line per event to
`<run>/traces.jsonl`: `on_chat_model_start/end` (agent name, messages in,
completion, token usage), `on_tool_start/end` (tool, args, result excerpt).
Passed via `config={"callbacks": [tracer], "run_name": "<agent>"}` to every
agent invocation, so each trace line is attributable. Plus
`jetai trace [--run DIR]` (defaults to latest run): prints a per-agent
summary table (calls, tokens, tools used) and `--full` to dump the raw lines.

### `models.py`
Shared pydantic models (all agents' `response_format`s live here):
- `ColumnProfile` (name, inferred_type, date_format, decimal_style, mixed,
  ambiguity_note) — filled by the deterministic format detector (§3.1)
- `FileProfile` (path, kind, rows, columns: list[ColumnProfile], header_row,
  encoding, description, candidate_keys, quality_notes) and `DatasetProfile`
- `AuditContext` (client, fiscal_year_end, approval_threshold_eur,
  materiality_eur, trivial_threshold_eur, special_rules: list[str],
  source_documents)
- `BuildReport` (tables_created: name→row count, canonical_views_present,
  mapping: canonical column → source file+column, unmapped, notes)
- `Finding` (check, category, **primary_entities: list[str]** — the
  accounts/documents/users actually accused, used by eval —
  amount_eur, period, evidence_sql: list[str], evidence_summary, confidence)
- `FindingsReport` (findings, checked_population, limitations)
- `FinalReport` (confirmed findings with verifier notes, rejected findings
  with reasons, tie_outs, summary)

### `tools.py`
- `make_execute_sql_tool(conn, *, max_rows=50)` — runs a query, returns a
  compact text table; row-capped so agents must aggregate, never dump; DuckDB
  errors returned as text for self-correction. One factory, bound read-write
  for the build agent and `read_only=True` connections for checks/verifier.
- `make_schema_tool(conn)` — lists tables/views with columns + 3 sample rows
  (the "inspect before you query" tool from the SQL-agent canon).
- `make_list_sources_tool(profile: DatasetProfile)` — returns one line per
  file: relative path, rows, and the profiler's one-sentence description, so
  downstream agents know what's in a file **without loading it**.
- `make_read_head_tool(root)` — first N lines of a source file (cap ~40
  lines), for the profiler and build agent only.
- `make_read_markdown_tool(root)` — full text of a converted `.md` document
  (working papers are short), for the audit-context agent.

## 3. The agents

All are `create_agent(model, tools, response_format=<model>)`, invoked with a
single self-contained brief message, `recursion_limit` 30–40, and the tracer
callback. Prompts are generic — they describe *what kind* of thing to find,
never *which* record to find.

### 3.1 Profiling agent (`profiling.py`)
Deterministic code first: walk the inventory, sniff encoding/delimiter, count
rows, detect the real header row (handles the xlsx title-row problem),
extract columns and 3 sample rows. Then **one** LLM pass over that digest
(`response_format=DatasetProfile`) adds per-file descriptions, candidate join
keys and quality notes. Writes `profile.json`. This is what makes every
downstream prompt schema-agnostic. Satisfies the "short explanation of what
is found in each file" requirement.

**Deterministic date/number format detection** (new module
`agents/formats.py`, part of the non-LLM pass): mixed standards are a real
risk — the native files are German-style (`DD.MM.YYYY`, decimal comma) but
our own xlsx→csv conversion emits decimal points and ISO timestamps, and a
foreign dataset may use `MM/DD/YYYY`. So the profiler classifies every
column's non-null values (cap ~5,000 samples) against a fixed
regex/strptime candidate set:
- dates: `%d.%m.%Y`, `%Y-%m-%d`, `%d/%m/%Y`, `%m/%d/%Y` + datetime/time
  variants
- numbers: German (`1.234,56` / `1234,56`), English (`1,234.56` /
  `1234.56`), bare integer

From the per-candidate match counts it derives, per column:
- `mixed=True` when ≥2 incompatible formats each exceed ~2% of values
  (a column that genuinely mixes standards);
- `ambiguous=True` when the data cannot discriminate — all day parts ≤ 12
  (`d/m` vs `m/d`) or integer-only amounts (decimal style undecidable) —
  resolved by a documented default (follow the rest of the file's style if
  unambiguous elsewhere, else flagged for the build agent).

Results land in each `ColumnProfile`; `jetai profile` prints a warning per
mixed/ambiguous column so format problems surface before any LLM runs.
Detection deliberately runs on the **post-conversion** files, so the profile
describes exactly what the build agent will load.

### 3.2 Audit-context agent (`audit_context.py`)
Tools: `read_markdown`, `list_sources`. Brief: "find the audit working papers
and rights/permissions documents in this dataset; extract thresholds,
materiality, special rules." Writes `audit_context.json`. This replaces
hardcoding the €10,000 threshold — on another dataset it reads whatever the
working paper there says.

### 3.3 Build agent (`build.py`)
Tools: `execute_sql` (read-write on `<run>/audit.duckdb`), `schema`,
`list_sources`, `read_head`. Brief: profile digest **including the detected
per-file/per-column formats (§3.1) as facts, not guesses** + the canonical
schema definition + `skip=<header_row>` when loading. The agent must pass
detected formats explicitly to DuckDB —
`read_csv(..., dateformat='%d.%m.%Y', decimal_separator=',')` (both native
`read_csv` parameters) — falling back to explicit `strptime`/`replace`
casts only for columns flagged `mixed`. The agent loads sources with DuckDB
`read_csv`, builds typed base tables, then the canonical views. Exact SQL is
the agent's call — that's what absorbs schema variation.
`run_build_agent` verifies **deterministically** afterwards and writes
`build_report.json`; the supervisor sees verification results, not the
agent's claims:
- `duckdb_tables()` + row counts > 0 for present views;
- **cast-residue check**: per typed table, count rows where a cast turned a
  non-NULL raw value into NULL (unparseable) — any nonzero count is a
  recorded defect;
- **date-range check**: date columns must fall within ±1 year of the fiscal
  year from `audit_context.json` — catches silently *wrong*
  day/month-swapped parses that cast "successfully".

### 3.4 Check agents (`checks.py`)
One generic runner + declarative specs — adding a check is adding a spec:

```python
@dataclass(frozen=True)
class CheckSpec:
    name: str                 # "three_way_match", ...
    required_views: tuple[str, ...]
    brief: str                # the generic audit-logic prompt
```

`run_check_agent(spec, db_path, audit_context) -> FindingsReport` — read-only
connection, tools `execute_sql` + `schema`, brief = spec.brief + audit
context (thresholds) + instruction to cite SQL evidence and name
`primary_entities`. Writes `findings/<name>.json`.

The five specs (all generic formulations):
1. **`three_way_match`** — invoices with payments but no goods receipt (and
   the reverse); amount mismatches; cross-check who created/approved the
   vendor and who booked/paid (needs `three_way_match`, `dim_vendor`,
   `master_data_changes`, `dim_user`).
2. **`cutoff`** — next-period invoices/postings with service dates in the
   audit year, goods received before year-end without accrual
   (`late_vendor_invoices`, `next_period_postings`, `goods_receipts`,
   `gl_postings`).
3. **`account_classification`** — expense-like items (repair/maintenance
   wording) capitalized to asset accounts; uses account *names* from
   `dim_account`/`dim_asset`, not hardcoded account numbers.
4. **`split_payments`** — multiple same-day/same-payee payments individually
   under the approval threshold from `audit_context` summing above it.
5. **`four_eyes`** — creator = approver in `approval_log` or
   `master_data_changes`; users whose combined rights (`dim_user`) break
   segregation of duties.

### 3.5 Verifier agent (`verifier.py`)
Tools: read-only `execute_sql` + `schema`. Input: **all `findings/*.json`
verbatim** (they are small structured lists — not supervisor paraphrase) +
audit context. Job: re-run/probe the cited evidence, actively look for
innocent explanations (the decoy defense: a "suspicious" new vendor with
proper approvals and real goods receipts is *clean*), merge duplicates across
checks (the same scheme often surfaces in several), check amounts against the
trivial threshold, and produce `FinalReport` → `report.json` + rendered
`report.md`. The decoy logic is generic — "verify before accusing" — with no
knowledge of which records are decoys.

### 3.6 Supervisor (`supervisor.py`)
`create_agent` whose tools wrap the runners above: `profile_dataset`,
`extract_audit_context`, `build_database`, `run_check(check_name)`,
`verify_findings`, plus `list_run_artifacts`. Each tool returns a compact
JSON summary (status, counts, artifact path, problems) — full artifacts stay
on disk. Prompt: the audit program, when to skip a check (required views
missing per build report), when to retry a failed build (at most once), and
to finish by calling `verify_findings`. `recursion_limit` ~50.

## 4. CLI (`cli.py`)

- `jetai audit [PATH]` — full supervisor run; prints the final report table
  (findings, entities, amounts, confidence) + run dir path.
- `jetai profile / build-db / check <name>|--all / verify [--run DIR]` —
  run stages standalone against an existing run dir for iteration.
- `jetai trace [--run DIR] [--full]` — inspect traces (see §2 tracing).
- `jetai eval [--run DIR]` — see §6.
- Existing `inventory` / `preprocess` unchanged in interface.

## 5. Housekeeping

- `pyproject.toml`: **remove `anthropic`**; add `duckdb>=1.5`,
  `langchain>=1.0`, `langgraph>=1.2`, `langchain-openai>=1.3`; register the
  `integration` pytest marker. `runs/` added to `.gitignore`.
- `tools.md`: slim it to a terse command reference (one short block per CLI
  command incl. the new ones, plus a 3-line note on reading `traces.jsonl`
  with `jq`); move the pdfplumber rationale into `preprocess.py`'s docstring
  where it already half-lives.

## 6. Evaluation

Ground truth lives in `eval/ground_truth.json` — derived from `solution.md`,
**never imported by `src/`** (agents must not be able to see it):

```json
{
  "expected": [
    {"id": "F1", "check_any": ["three_way_match", "four_eyes"],
     "must_mention_any": ["209101"]},
    {"id": "F2", "check_any": ["account_classification"],
     "must_mention_any": ["040000", "060000"]},
    {"id": "F3", "check_any": ["cutoff"], "must_mention_any": ["209130", "..."]},
    {"id": "F4", "check_any": ["split_payments"], "must_mention_any": ["200007"]}
  ],
  "decoys": [{"id": "D1", "entities": ["..."]}, "... D2–D7 entity lists ..."]
}
```

`src/jetai/evaluation.py` + `jetai eval`: load a run's `report.json`, score
deterministically — an expected finding is *caught* if a confirmed finding
from an allowed check names one of its entities in `primary_entities`; a
decoy is *accused* if its entity appears in any confirmed finding's
`primary_entities`. Output: recall on F1–F3, F4 as bonus, decoy accusations
as penalty, precision, and a per-finding table — mirroring `solution.md`'s
scoring rubric. No LLM judge needed because outputs are structured.

Per-agent evaluation comes free from the same harness: `jetai check
three_way_match --run DIR && jetai verify --run DIR && jetai eval --run DIR`
iterates one check against a cached `audit.duckdb` without rerunning the
pipeline.

## 7. Tests

- Unit (no LLM, run in CI): GDPdU parsing/conversion round-trip on a tiny
  synthetic `index.xml`+`.txt` fixture (umlauts, mismatched row); header-row
  detection incl. title-row xlsx; `tests/test_formats.py` — the format
  detector on German, English, ISO, genuinely mixed (comma+point), ambiguous
  `d/m` (all days ≤12), integer-only, and datetime/time-only columns,
  asserting format string / decimal style / `mixed` / `ambiguous` flags;
  `execute_sql` capping + error passthrough; `JsonlTracer` event writing;
  evaluation scoring on a fabricated report (catches, decoy accusation,
  miss).
- Integration (`-m integration`, skipif no `OPENAI_API_KEY`):
  - per-agent: profiler describes every file; build produces the canonical
    views with sane row counts (~2.5k `three_way_match` rows); each check on
    the prebuilt DB; verifier keeps a planted true finding and drops a
    planted unsupported one.
  - end-to-end: `jetai audit data` then assert the eval scorecard: F1 caught,
    zero decoys accused (the honest-twin vendor must survive).
  - **generalization smoke test**: a committed mini-fixture
    (`tests/fixtures/alt_dataset/`, ~30 rows) mimicking a *different*
    accounting software — English file/column names
    (`vendors.csv`, `ap_postings.csv`, `goods_receipts.csv`, headers
    included, ISO dates, decimal points), one planted invoice-without-receipt.
    Assert: profile → build → `three_way_match` check still flags it. This is
    the empirical test of the whole generalization claim.

## 8. Build order & verification

1. Preprocessing extension + profiler → `jetai profile data` describes all
   files (checkpoint: xlsx title rows correctly detected).
2. Build agent → open `audit.duckdb`, spot-check `three_way_match` (~2.5k
   rows; the five receipt-less consulting invoices appear with NULL receipt
   columns — visible in SQL, not asserted anywhere in code).
3. First check (`three_way_match`) + verifier + eval harness → first
   scorecard.
4. Remaining four checks (specs only — runner already exists).
5. Supervisor + `jetai audit` end-to-end; alt-dataset generalization test.
6. Throughout: `pytest`, `ruff check .`, `mypy` stay green (strict mode
   already enforced); traces reviewed after every integration run via
   `jetai trace`.
