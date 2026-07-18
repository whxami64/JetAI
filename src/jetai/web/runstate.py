"""Lifecycle of a web-triggered audit run: ZIP intake and background execution.

The UI uploads a ZIP, we extract it to a fresh ``uploads/<stamp>/`` directory
(so :func:`jetai.preprocess.preprocess_dataset` can mutate it freely) and run
the supervisor in a daemon thread while the frontend tails ``traces.jsonl``.
"""

from __future__ import annotations

import threading
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jetai.agents.config import AgentSettings, create_run_dir
from jetai.agents.supervisor import run_supervisor
from jetai.dataset import find_dataset_root
from jetai.preprocess import preprocess_dataset

UPLOADS_DIR = Path("uploads")

# One audit at a time: the supervisor is expensive and the run dirs are global.
_run_lock = threading.Lock()


class RunError(RuntimeError):
    """A user-facing problem with starting or executing a run."""


@dataclass
class AuditRun:
    """Mutable state of one background audit run, shared with the UI thread."""

    dataset_root: Path
    run_dir: Path
    phase: str = "starting"  # preprocessing | running | done | failed
    summary: str | None = None
    error: str | None = None
    thread: threading.Thread = field(init=False)

    @property
    def failed(self) -> bool:
        return self.phase == "failed"

    @property
    def finished(self) -> bool:
        return self.phase in ("done", "failed")


def extract_zip(zip_path: Path, uploads_dir: Path = UPLOADS_DIR) -> Path:
    """Extract an uploaded ZIP into a fresh ``uploads/<UTC stamp>/`` directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = uploads_dir / stamp
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                member_path = Path(member)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise RunError(f"ZIP contains an unsafe path: {member}")
            target.mkdir(parents=True, exist_ok=False)
            archive.extractall(target)
    except zipfile.BadZipFile as error:
        raise RunError("The uploaded file is not a valid ZIP archive.") from error
    return target


def start_audit(
    settings: AgentSettings, zip_path: Path, uploads_dir: Path = UPLOADS_DIR
) -> AuditRun:
    """Extract the ZIP, create a run dir and launch the audit in a thread."""
    if not _run_lock.acquire(blocking=False):
        raise RunError("An audit run is already in progress; wait for it to finish.")
    try:
        extract_dir = extract_zip(zip_path, uploads_dir)
        try:
            root = find_dataset_root(extract_dir)
        except FileNotFoundError as error:
            raise RunError(str(error)) from error
        run_dir = create_run_dir(settings.runs_dir)
    except BaseException:
        _run_lock.release()
        raise

    audit = AuditRun(dataset_root=root, run_dir=run_dir, phase="preprocessing")

    def _work() -> None:
        try:
            preprocess_dataset(audit.dataset_root)
            audit.phase = "running"
            audit.summary = run_supervisor(settings, audit.dataset_root, audit.run_dir)
            audit.phase = "done"
        except Exception:  # noqa: BLE001 - surfaced verbatim in the UI
            audit.error = traceback.format_exc()
            audit.phase = "failed"
        finally:
            _run_lock.release()

    audit.thread = threading.Thread(target=_work, name="jetai-audit", daemon=True)
    audit.thread.start()
    return audit
