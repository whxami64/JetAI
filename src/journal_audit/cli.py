"""Command line entry point for the journal audit agent."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from journal_audit import __version__
from journal_audit.dataset import build_inventory, find_dataset_root

app = typer.Typer(help="Journal entry testing (JET) audit agent.", no_args_is_help=True)
console = Console()


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"journal-audit {__version__}")


@app.command()
def inventory(
    path: Path = typer.Argument(
        Path("data"),
        help="Dataset directory, or a parent containing one (e.g. ./data).",
    ),
) -> None:
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


if __name__ == "__main__":
    app()
