"""Append-only response archive. Normal startup never removes existing runs."""

import fcntl
import gzip
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(UTC)


class Discovery(BaseModel):
    product_id: str
    edition_url: str


class Snapshot(BaseModel):
    snapshot_id: int
    requested_url: str
    final_url: str | None
    fetched_at: datetime
    status: int | None
    sha256: str | None
    body_ref: str | None
    attempt: int
    error: str | None = None
    products: list[Discovery] = Field(default_factory=list)


class RunManifest(BaseModel):
    archive_version: int = 1
    store: str
    run_id: int
    scope: str
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    complete: bool = False
    snapshots: list[Snapshot] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    listing_count: int = 0
    product_count: int = 0


class StoreBusyError(RuntimeError):
    """Another process holds this store's ingestion lock."""


class ArchivedRun:
    def __init__(self, path: Path, manifest: RunManifest) -> None:
        self.path = path
        self.manifest = manifest
        self.save()

    def save(self) -> None:
        temporary = self.path / "manifest.json.tmp"
        temporary.write_text(self.manifest.model_dump_json(indent=2) + "\n")
        temporary.replace(self.path / "manifest.json")

    def record(
        self,
        requested_url: str,
        *,
        final_url: str | None,
        status: int | None,
        body: bytes | None,
        attempt: int,
        error: str | None = None,
    ) -> Snapshot:
        snapshot_id = len(self.manifest.snapshots) + 1
        body_ref = f"{snapshot_id:06d}.html.gz" if body is not None else None
        if body_ref is not None and body is not None:
            with (self.path / body_ref).open("xb") as file:
                file.write(gzip.compress(body, mtime=0))
        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            requested_url=requested_url,
            final_url=final_url,
            fetched_at=now(),
            status=status,
            sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
            body_ref=body_ref,
            attempt=attempt,
            error=error,
        )
        self.manifest.snapshots.append(snapshot)
        self.save()
        return snapshot


class RawArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def start(self, store: str, scope: str) -> Iterator[ArchivedRun]:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", store):
            raise ValueError("Invalid store key")
        directory = self.root / store
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StoreBusyError(f"An ingestion run is already active for {store}") from error
            try:
                run_id = 1 + max(
                    (int(p.name) for p in directory.iterdir() if p.is_dir() and p.name.isdigit()),
                    default=0,
                )
                path = directory / str(run_id)
                path.mkdir()
                run = ArchivedRun(path, RunManifest(store=store, run_id=run_id, scope=scope))
                try:
                    yield run
                except BaseException as error:
                    run.manifest.complete = False
                    run.manifest.failures.append(f"Interrupted: {type(error).__name__}: {error}")
                    raise
                finally:
                    run.manifest.finished_at = now()
                    run.save()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
