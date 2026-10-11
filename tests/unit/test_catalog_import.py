"""Catalog schema and idempotent import tests. Temporary SQLite, no network."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from cdon_watcher.catalog.db import (
    CURRENT_VERSION,
    SchemaError,
    create_catalog_engine,
    current_version,
    migrate,
    open_catalog,
)
from cdon_watcher.catalog.importer import import_run
from cdon_watcher.catalog.models import (
    CrawlRun,
    PriceObservation,
    SchemaVersion,
    Store,
    StoreProduct,
)
from cdon_watcher.ingestion.contract import (
    Availability,
    Condition,
    Format,
    ParsedProduct,
    ParsedRun,
    ParsedSnapshot,
    ParseError,
)

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


def product(product_id="1", store="ax", price=999, regular=1299, fmt=Format.BLURAY, **extra):
    fields = dict(
        store=store,
        product_id=product_id,
        raw_title=f"Movie {product_id}",
        cleaned_title=f"Movie {product_id}",
        edition_url=f"https://example.test/movie/{product_id}/#{product_id}",
        format=fmt,
        format_raw="Blu-Ray",
        condition=Condition.NEW,
        availability=Availability.IN_STOCK,
        availability_raw="Tuotetta hyllyssä, toimitus heti",
        price_cents=price,
        regular_price_cents=regular,
    )
    fields.update(extra)
    return ParsedProduct(**fields)


def run(run_id, products, *, store="ax", complete=True, errors=(), day=0):
    fetched = T0 + timedelta(days=day)
    return ParsedRun(
        store=store,
        run_id=run_id,
        parser_version="ax-1",
        complete=complete,
        parsed_at=fetched,
        snapshots=[
            ParsedSnapshot(
                snapshot_id=1,
                requested_url="https://example.test/offer/",
                fetched_at=fetched,
                products=list(products),
                errors=list(errors),
            )
        ],
    )


@pytest.fixture
def engine(tmp_path):
    return open_catalog(tmp_path / "catalog.db")


def products(engine, store="ax"):
    with Session(engine) as session:
        rows = session.exec(
            select(StoreProduct)
            .join(Store)
            .where(Store.key == store)
            .order_by(StoreProduct.product_id)  # type: ignore[arg-type]
        ).all()
        session.expunge_all()
        return rows


def observations(engine):
    with Session(engine) as session:
        rows = session.exec(
            select(PriceObservation).order_by(
                PriceObservation.store_product_id,  # type: ignore[arg-type]
                PriceObservation.run_id,  # type: ignore[arg-type]
            )
        ).all()
        session.expunge_all()
        return rows


def test_migrations_are_versioned_and_refuse_newer_databases(tmp_path):
    engine = create_catalog_engine(tmp_path / "c.db")
    assert current_version(engine) == 0
    assert migrate(engine) == CURRENT_VERSION
    assert migrate(engine) == CURRENT_VERSION
    with Session(engine) as session:
        session.add(SchemaVersion(version=CURRENT_VERSION + 1, applied_at=T0))
        session.commit()
    with pytest.raises(SchemaError):
        migrate(engine)


def test_first_import_creates_store_products_observations_and_run(engine):
    result = import_run(engine, run(1, [product("1"), product("2", price=1500, regular=None)]))
    assert (result.products_created, result.observations_created, result.expired) == (2, 2, 0)
    rows = products(engine)
    assert [(p.product_id, p.current_price_cents, p.active) for p in rows] == [
        ("1", 999, True),
        ("2", 1500, True),
    ]
    assert rows[0].first_seen_at.replace(tzinfo=UTC) == T0
    assert rows[0].last_seen_run_id == 1
    assert rows[1].current_regular_price_cents is None
    with Session(engine) as session:
        crawl = session.exec(select(CrawlRun)).one()
        assert (crawl.run_id, crawl.complete, crawl.product_count) == (1, True, 2)


def test_replay_is_idempotent_and_keeps_observed_at(engine):
    first = import_run(engine, run(1, [product("1")]))
    before = observations(engine)
    again = import_run(engine, run(1, [product("1", price=899)]), now=T0 + timedelta(days=9))
    after = observations(engine)
    assert (first.observations_created, again.observations_created) == (1, 0)
    assert again.observations_updated == 1
    assert len(after) == 1
    assert after[0].observed_at == before[0].observed_at
    assert after[0].price_cents == 899
    assert products(engine)[0].current_price_cents == 899
    with Session(engine) as session:
        assert len(session.exec(select(CrawlRun)).all()) == 1


def test_newer_run_appends_history_and_older_run_does_not_overwrite_current(engine):
    import_run(engine, run(1, [product("1", price=999)]))
    import_run(engine, run(2, [product("1", price=799)], day=1))
    assert products(engine)[0].current_price_cents == 799
    assert [o.price_cents for o in observations(engine)] == [999, 799]
    # Reprocess the old run with a parser fix: history updates, current state does not.
    import_run(engine, run(1, [product("1", price=1099)]))
    assert products(engine)[0].current_price_cents == 799
    assert products(engine)[0].last_seen_run_id == 2
    assert [o.price_cents for o in observations(engine)] == [1099, 799]


def test_complete_run_expires_unseen_products_only(engine):
    import_run(engine, run(1, [product("1"), product("2")]))
    result = import_run(engine, run(2, [product("1")], day=1), now=T0 + timedelta(days=1))
    assert result.expired == 1
    rows = products(engine)
    assert [(p.product_id, p.active) for p in rows] == [("1", True), ("2", False)]
    assert rows[1].inactive_since is not None
    # Seen again later: reactivated.
    import_run(engine, run(3, [product("1"), product("2")], day=2))
    assert all(p.active for p in products(engine))
    assert products(engine)[1].inactive_since is None


def test_incomplete_run_imports_but_never_expires(engine):
    import_run(engine, run(1, [product("1"), product("2")]))
    result = import_run(engine, run(2, [product("1", price=500)], complete=False, day=1))
    assert (result.expired, result.observations_created) == (0, 1)
    assert [(p.product_id, p.active) for p in products(engine)] == [("1", True), ("2", True)]
    assert products(engine)[0].current_price_cents == 500


def test_parse_error_is_not_evidence_of_disappearance(engine):
    import_run(engine, run(1, [product("1"), product("2")]))
    result = import_run(
        engine,
        run(2, [product("1")], errors=[ParseError(product_id="2", reason="bad price")], day=1),
    )
    assert (result.expired, result.errors) == (0, 1)
    assert all(p.active for p in products(engine))


def test_reprocessing_old_complete_run_does_not_expire_newer_products(engine):
    import_run(engine, run(1, [product("1")]))
    import_run(engine, run(2, [product("1"), product("2")], day=1))
    result = import_run(engine, run(1, [product("1")]))
    assert result.expired == 0
    assert all(p.active for p in products(engine))


def test_store_scoped_ids_and_isolated_expiry(engine):
    import_run(engine, run(1, [product("1", store="ax")]))
    import_run(engine, run(1, [product("1", store="cdon", price=2000)], store="cdon"))
    assert products(engine, "ax")[0].current_price_cents == 999
    assert products(engine, "cdon")[0].current_price_cents == 2000
    assert len(observations(engine)) == 2
    # A complete Äx run that sees nothing must not touch CDON.
    import_run(engine, run(2, [], day=1))
    assert products(engine, "ax")[0].active is False
    assert products(engine, "cdon")[0].active is True


def test_ineligible_products_are_skipped(engine):
    result = import_run(engine, run(1, [product("1", fmt=Format.DVD), product("2")]))
    assert (result.skipped_ineligible, result.products_created) == (1, 1)


def test_import_cli(tmp_path, monkeypatch, capsys):
    from cdon_watcher.cli import main

    raw = tmp_path / "raw" / "ax" / "3"
    raw.mkdir(parents=True)
    (raw / "parsed.json").write_text(run(3, [product("1")]).model_dump_json())
    db = tmp_path / "catalog.db"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cdon-watcher",
            "import-run",
            "--store",
            "ax",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--db",
            str(db),
        ],
    )
    main()
    assert "run 3 (complete): 1 products (1 new), 1 observations added" in capsys.readouterr().out
    assert len(products(open_catalog(db))) == 1


def test_import_cli_without_parsed_run_exits_2(tmp_path, monkeypatch):
    from cdon_watcher.cli import main

    (tmp_path / "raw" / "ax" / "1").mkdir(parents=True)
    monkeypatch.setattr(
        "sys.argv",
        ["cdon-watcher", "import-run", "--store", "ax", "--raw-dir", str(tmp_path / "raw")],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
