"""Transactional, immutable PostgreSQL evidence repository; no SQLite substitution."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from backend.app.db.models import cases, catalogs, operations, trials


class ConflictError(ValueError):
    pass


class EvidenceError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def local_engine(url, **kwargs):
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.query
    ):
        raise ValueError(
            "only a local PostgreSQL/psycopg database URL without query overrides is allowed"
        )
    return create_engine(
        parsed,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=0,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, **kwargs},
    )


def migrate(engine):
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "db/migrations"))
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(10928371)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def checked(row):
    if row is None:
        return None
    if digest(row["payload"]) != row["sha256"]:
        raise EvidenceError("stored evidence checksum mismatch")
    return row["payload"]


def put(connection, table, keys, payload, **columns):
    checksum = digest(payload)
    connection.execute(
        insert(table)
        .values(**keys, sha256=checksum, payload=payload, **columns)
        .on_conflict_do_nothing(index_elements=list(keys))
    )
    row = connection.execute(select(table).filter_by(**keys)).mappings().one()
    if checked(row) != payload:
        raise ConflictError("immutable record differs; use a new versioned identity")
    return payload


class PostgresStore:
    def __init__(self, engine, catalog_id="bounded-api-v1"):
        self.engine, self.catalog_id = engine, catalog_id

    def ready(self):
        with self.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            catalog = checked(
                connection.execute(select(catalogs).where(catalogs.c.id == self.catalog_id))
                .mappings()
                .first()
            )
            if revision != "0001_catalogs" or catalog is None:
                raise EvidenceError("database revision/catalog is not ready")
            return {
                "status": "ready",
                "revision": revision,
                "server_version": connection.execute(text("SHOW server_version")).scalar_one(),
            }

    def catalog(self):
        with self.engine.connect() as c:
            return checked(
                c.execute(select(catalogs).where(catalogs.c.id == self.catalog_id))
                .mappings()
                .first()
            )

    def seed(self, catalog, case_records, trial_records):
        with self.engine.begin() as c:
            put(c, catalogs, {"id": self.catalog_id}, catalog)
            for table, rows in ((cases, case_records), (trials, trial_records)):
                for record_id, payload in rows.items():
                    put(c, table, {"catalog_id": self.catalog_id, "id": record_id}, payload)

    def get(self, kind, record_id):
        table = {"cases": cases, "trials": trials, "operations": operations}[kind]
        with self.engine.connect() as c:
            return checked(
                c.execute(
                    select(table).where(
                        table.c.catalog_id == self.catalog_id, table.c.id == record_id
                    )
                )
                .mappings()
                .first()
            )

    def page(self, kind, limit, offset):
        if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
            raise ValueError("invalid page bounds")
        table = {"cases": cases, "trials": trials, "operations": operations}[kind]
        with self.engine.connect() as c:
            query = select(table).where(table.c.catalog_id == self.catalog_id)
            rows = (
                c.execute(query.order_by(table.c.id).limit(limit).offset(offset)).mappings().all()
            )
            total = c.execute(
                select(func.count()).select_from(table).where(table.c.catalog_id == self.catalog_id)
            ).scalar_one()
            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": [{"id": r["id"], "payload": checked(r)} for r in rows],
            }

    def save_operation(self, operation_id, kind, request, payload):
        with self.engine.begin() as c:
            return put(
                c,
                operations,
                {"id": operation_id},
                payload,
                catalog_id=self.catalog_id,
                kind=kind,
                request=request,
            )
