"""Offline parse stage: archived run in, parsed products out. No network."""

import gzip
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .archive import RunManifest
from .contract import ParsedProduct, ParsedRun, ParsedSnapshot, ParseError

PARSED_FILENAME = "parsed.json"


class StoreParser(Protocol):
    store: str
    version: str
    expires_unseen: bool

    def parse(self, body: bytes) -> tuple[list[ParsedProduct], list[ParseError]]: ...


def latest_run_id(root: Path, store: str) -> int:
    directory = root / store
    runs = [int(p.name) for p in directory.iterdir() if p.is_dir() and p.name.isdigit()]
    if not runs:
        raise FileNotFoundError(f"No archived runs for store {store!r} under {directory}")
    return max(runs)


def load_manifest(root: Path, store: str, run_id: int) -> tuple[Path, RunManifest]:
    path = root / store / str(run_id)
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No manifest for run {run_id} of store {store!r}")
    return path, RunManifest.model_validate_json(manifest_path.read_text())


def parse_run(
    root: Path,
    parser: StoreParser,
    run_id: int | None = None,
    *,
    eligible_only: bool = True,
) -> ParsedRun:
    """Parse every successfully discovered snapshot of one run and save parsed.json.

    Reparsing the same run overwrites its parsed result. The raw responses and
    manifest are never modified. Products seen in more than one snapshot keep
    their first occurrence.
    """
    if run_id is None:
        run_id = latest_run_id(root, parser.store)
    path, manifest = load_manifest(root, parser.store, run_id)
    if manifest.store != parser.store:
        raise ValueError(f"Manifest store {manifest.store!r} does not match parser")

    seen: set[str] = set()
    result = ParsedRun(
        store=parser.store,
        run_id=run_id,
        parser_version=parser.version,
        complete=manifest.complete,
        parsed_at=datetime.now(UTC),
        expire_unseen=parser.expires_unseen,
    )
    for snapshot in manifest.snapshots:
        if snapshot.error is not None or snapshot.body_ref is None or snapshot.status != 200:
            continue
        body = gzip.decompress((path / snapshot.body_ref).read_bytes())
        products, errors = parser.parse(body)
        kept: list[ParsedProduct] = []
        for product in products:
            if product.product_id in seen:
                continue
            seen.add(product.product_id)
            if eligible_only and not product.eligible:
                continue
            kept.append(product)
        result.snapshots.append(
            ParsedSnapshot(
                snapshot_id=snapshot.snapshot_id,
                requested_url=snapshot.requested_url,
                fetched_at=snapshot.fetched_at,
                products=kept,
                errors=errors,
            )
        )

    temporary = path / (PARSED_FILENAME + ".tmp")
    temporary.write_text(result.model_dump_json(indent=2) + "\n")
    temporary.replace(path / PARSED_FILENAME)
    return result


def load_parsed(root: Path, store: str, run_id: int) -> ParsedRun:
    return ParsedRun.model_validate_json((root / store / str(run_id) / PARSED_FILENAME).read_text())
