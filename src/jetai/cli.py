"""Command line entry point for the journal audit agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from jetai import __version__

if TYPE_CHECKING:
    from jetai.agents.config import AgentSettings
    from jetai.agents.models import FinalReport
from jetai.dataset import build_inventory, find_dataset_root
from jetai.preprocess import preprocess_dataset

app = typer.Typer(help="Journal entry testing (JET) audit agent.", no_args_is_help=True)
console = Console()

_PATH_ARGUMENT = typer.Argument(
    Path("data"),
    help="Dataset directory, or a parent containing one (e.g. ./data).",
)
_RUN_OPTION = typer.Option(
    None, "--run", help="Existing run directory to reuse (defaults to the latest run)."
)


def _settings() -> AgentSettings:
    from jetai.agents.config import AgentSettings

    try:
        return AgentSettings()  # type: ignore[call-arg]  # loaded from env/.env
    except ValidationError:
        console.print(
            "[red]Missing OpenAI configuration.[/red] "
            "Copy .env.example to .env and set OPENAI_API_KEY."
        )
        raise typer.Exit(1) from None


def _resolve_run(run: Path | None) -> Path:
    from jetai.agents.config import latest_run_dir

    if run is not None:
        if not run.is_dir():
            console.print(f"[red]Run directory not found:[/red] {run}")
            raise typer.Exit(1)
        return run
    try:
        return latest_run_dir(_settings().runs_dir)
    except FileNotFoundError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"jetai {__version__}")


@app.command()
def inventory(path: Path = _PATH_ARGUMENT) -> None:
    """List the source documents discovered in a dataset, grouped by kind."""
    root = find_dataset_root(path)
    found = build_inventory(root)

    table = Table(title=f"Sources under {root.name}")
    table.add_column("Kind", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("GDPdU ledgers", str(len(found.ledgers)))
    table.add_row("Tables (csv/xlsx)", str(len(found.tables)))
    table.add_row("Documents (docx/pdf)", str(len(found.documents)))
    console.print(table)


@app.command()
def preprocess(path: Path = _PATH_ARGUMENT) -> None:
    """Convert GDPdU txt/xlsx/docx/pdf sources to csv/markdown and archive originals."""
    root = find_dataset_root(path)
    result = preprocess_dataset(root)

    table = Table(title=f"Preprocessed {root.name}")
    table.add_column("Written", justify="right")
    table.add_column("Archived to stale/", justify="right")
    table.add_row(str(len(result.converted)), str(len(result.archived)))
    console.print(table)

    for out in result.converted:
        console.print(f"  [green]+[/green] {out.relative_to(root)}")
    for archived in result.archived:
        console.print(f"  [yellow]->[/yellow] {archived.relative_to(root)}")
    for out, count in result.mismatched_rows.items():
        console.print(
            f"  [red]![/red] {out.relative_to(root)}: {count} rows mismatch the descriptor"
        )


@app.command()
def profile(path: Path = _PATH_ARGUMENT, run: Path | None = _RUN_OPTION) -> None:
    """Profile every source file (deterministic survey + one LLM pass)."""
    from jetai.agents.config import create_run_dir
    from jetai.agents.profiling import run_profiling_agent

    settings = _settings()
    root = find_dataset_root(path)
    if run is not None and not run.is_dir():
        console.print(f"[red]Run directory not found:[/red] {run}")
        raise typer.Exit(1)
    run_dir = run if run is not None else create_run_dir(settings.runs_dir)
    result = run_profiling_agent(settings, root, run_dir)

    table = Table(title=f"Profile of {root.name} -> {run_dir}")
    table.add_column("File", style="cyan")
    table.add_column("Rows", justify="right")
    table.add_column("Description")
    for file in result.files:
        table.add_row(file.path, str(file.rows), file.description)
    console.print(table)
    for file in result.files:
        for column in file.columns:
            if column.mixed or column.ambiguous:
                flag = "mixed" if column.mixed else "ambiguous"
                console.print(
                    f"[yellow]warning:[/yellow] {file.path}:{column.name} [{flag}] {column.note}"
                )


@app.command()
def context(path: Path = _PATH_ARGUMENT, run: Path | None = _RUN_OPTION) -> None:
    """Extract audit context (thresholds, rules) from the working papers."""
    from jetai.agents.audit_context import run_audit_context_agent
    from jetai.agents.profiling import load_profile

    settings = _settings()
    root = find_dataset_root(path)
    run_dir = _resolve_run(run)
    result = run_audit_context_agent(settings, root, load_profile(run_dir), run_dir)
    console.print_json(result.model_dump_json())


@app.command("build-db")
def build_db(path: Path = _PATH_ARGUMENT, run: Path | None = _RUN_OPTION) -> None:
    """Build the canonical DuckDB views from the profiled sources."""
    from jetai.agents.audit_context import load_audit_context
    from jetai.agents.build import run_build_agent
    from jetai.agents.profiling import load_profile

    settings = _settings()
    root = find_dataset_root(path)
    run_dir = _resolve_run(run)
    report = run_build_agent(
        settings, root, load_profile(run_dir), load_audit_context(run_dir), run_dir
    )

    table = Table(title=f"Build report -> {run_dir}")
    table.add_column("View", style="cyan")
    table.add_column("Rows", justify="right")
    table.add_column("Defects")
    for check in report.view_checks:
        if not check.present:
            table.add_row(check.view, "-", "[red]missing[/red]")
            continue
        defects = [f"{c}: {n} NULLs" for c, n in check.null_defects.items()]
        defects += check.date_range_defects
        table.add_row(check.view, str(check.row_count), "; ".join(defects))
    console.print(table)


@app.command()
def check(
    name: str = typer.Argument("", help="Check name, or empty with --all."),
    run: Path | None = _RUN_OPTION,
    run_all: bool = typer.Option(False, "--all", help="Run every check."),
) -> None:
    """Run one check agent (or all of them) against the built database."""
    from jetai.agents.audit_context import load_audit_context
    from jetai.agents.checks import CHECK_SPECS, run_check_agent
    from jetai.agents.profiling import load_profile

    settings = _settings()
    run_dir = _resolve_run(run)
    names = sorted(CHECK_SPECS) if run_all else [name]
    if not run_all and name not in CHECK_SPECS:
        console.print(f"[red]Unknown check[/red] {name!r}; choose from {sorted(CHECK_SPECS)}")
        raise typer.Exit(1)
    audit_context = load_audit_context(run_dir)
    profile = load_profile(run_dir)
    dataset_root = Path(profile.root)
    for check_name in names:
        report = run_check_agent(
            settings, CHECK_SPECS[check_name], audit_context, run_dir, dataset_root, profile
        )
        console.print(
            f"[cyan]{check_name}[/cyan]: {len(report.findings)} findings "
            f"-> findings/{check_name}.json"
        )
        for finding in report.findings:
            entities = ", ".join(finding.primary_entities)
            console.print(f"  - [{finding.confidence}] {finding.category}: {entities}")


@app.command()
def verify(run: Path | None = _RUN_OPTION) -> None:
    """Verify all findings and produce the final report."""
    from jetai.agents.audit_context import load_audit_context
    from jetai.agents.verifier import run_verifier_agent

    settings = _settings()
    run_dir = _resolve_run(run)
    report = run_verifier_agent(settings, load_audit_context(run_dir), run_dir)
    _print_final_report(report, run_dir)


def _print_final_report(report: FinalReport, run_dir: Path) -> None:
    table = Table(title=f"Final report -> {run_dir}")
    table.add_column("Check", style="cyan")
    table.add_column("Category")
    table.add_column("Entities")
    table.add_column("EUR", justify="right")
    table.add_column("Confidence")
    for item in report.confirmed:
        finding = item.finding
        table.add_row(
            finding.check,
            finding.category,
            ", ".join(finding.primary_entities),
            f"{finding.amount_eur:,.0f}" if finding.amount_eur else "-",
            finding.confidence,
        )
    console.print(table)
    if report.rejected:
        console.print(f"[dim]{len(report.rejected)} findings rejected by the verifier.[/dim]")
    console.print(report.summary)


@app.command()
def audit(path: Path = _PATH_ARGUMENT) -> None:
    """Run the full audit program under the supervisor agent."""
    from jetai.agents.config import create_run_dir
    from jetai.agents.supervisor import run_supervisor
    from jetai.agents.verifier import load_report

    settings = _settings()
    root = find_dataset_root(path)
    preprocess_result = preprocess_dataset(root)
    if preprocess_result.converted:
        console.print(f"[dim]Preprocessed {len(preprocess_result.converted)} files.[/dim]")
    run_dir = create_run_dir(settings.runs_dir)
    console.print(f"Run directory: {run_dir}")
    summary = run_supervisor(settings, root, run_dir)
    console.print(summary)
    if (run_dir / "report.json").exists():
        _print_final_report(load_report(run_dir), run_dir)


@app.command()
def trace(
    run: Path | None = _RUN_OPTION,
    full: bool = typer.Option(False, "--full", help="Dump raw trace lines."),
) -> None:
    """Summarize (or dump) the run's traces.jsonl."""
    from jetai.agents.tracing import summarize_traces

    run_dir = _resolve_run(run)
    path = run_dir / "traces.jsonl"
    if full:
        if path.exists():
            console.print(path.read_text(encoding="utf-8"))
        return
    table = Table(title=f"Traces {path}")
    table.add_column("Agent", style="cyan")
    table.add_column("LLM calls", justify="right")
    table.add_column("Tool calls", justify="right")
    table.add_column("Tokens in", justify="right")
    table.add_column("Tokens out", justify="right")
    table.add_column("Tools used")
    for stats in summarize_traces(path):
        table.add_row(
            stats["agent"],
            str(stats["llm_calls"]),
            str(stats["tool_calls"]),
            str(stats["input_tokens"]),
            str(stats["output_tokens"]),
            ", ".join(stats["tools"]),
        )
    console.print(table)


@app.command("eval")
def eval_run(
    run: Path | None = _RUN_OPTION,
    truth: Path = typer.Option(
        Path("eval/ground_truth.json"), "--truth", help="Ground truth file."
    ),
) -> None:
    """Score a run's final report against the ground truth."""
    from jetai.agents.verifier import load_report
    from jetai.evaluation import load_ground_truth, score_report

    run_dir = _resolve_run(run)
    card = score_report(load_report(run_dir), load_ground_truth(truth))

    table = Table(title=f"Evaluation of {run_dir}")
    table.add_column("Expected", style="cyan")
    table.add_column("Caught", justify="center")
    table.add_column("Matched entities")
    for result in card.expected:
        mark = "[green]yes[/green]" if result.caught else "[red]no[/red]"
        label = result.id if result.core else f"{result.id} (bonus)"
        table.add_row(label, mark, ", ".join(result.matched_entities))
    for decoy_result in card.decoys:
        if decoy_result.accused:
            table.add_row(
                f"[red]decoy {decoy_result.id}[/red]",
                "[red]accused[/red]",
                ", ".join(decoy_result.matched_entities),
            )
    console.print(table)
    console.print(
        f"core recall {card.core_recall:.0%} · bonus {card.bonus_caught} · "
        f"decoys accused {card.decoys_accused} · precision {card.precision:.0%} · "
        f"{card.confirmed_findings} confirmed findings"
    )
    console.print(json.dumps(card.model_dump(), indent=2))


if __name__ == "__main__":
    app()
