# jetai CLI

## Setup

```bash
uv sync
source .venv/bin/activate
```

## `jetai inventory [PATH]`

Lists the source documents found under a dataset, grouped by kind (GDPdU
ledgers / tables / documents). `PATH` defaults to `data`.

```bash
jetai inventory data
```

## `jetai preprocess [PATH]`

Converts source documents into greppable text and archives the originals:

- `.xlsx` → `;`-separated `.csv` (one file per sheet; multi-sheet workbooks
  are named `<stem>__<SheetName>.csv`)
- `.docx` / `.pdf` → `.md`
- Converted originals are moved to `<dataset root>/stale/<relative path>`

```bash
jetai preprocess data
```

Safe to re-run: files already under `stale/` are excluded from the scan, so a
second run finds nothing left to convert.

PDF text is extracted with `pdfplumber` rather than markitdown's default pdf
backend, which scrambles label/value table layouts (e.g. financial
statements) into separate label and value blocks.
