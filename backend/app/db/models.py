"""Immutable source catalogs and evidence-bearing API operations in PostgreSQL."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
catalogs = Table(
    "ctr_catalogs",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
)
cases = Table(
    "ctr_cases",
    metadata,
    Column("catalog_id", String(80), ForeignKey("ctr_catalogs.id"), primary_key=True),
    Column("id", String(120), primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
)
trials = Table(
    "ctr_trials",
    metadata,
    Column("catalog_id", String(80), ForeignKey("ctr_catalogs.id"), primary_key=True),
    Column("id", String(11), primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
)
operations = Table(
    "ctr_operations",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("catalog_id", String(80), ForeignKey("ctr_catalogs.id"), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("request", JSONB, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_ctr_operations_catalog_kind", operations.c.catalog_id, operations.c.kind)
