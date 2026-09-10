"""Explicit migrations; API startup never changes the database schema."""

from alembic import context

from backend.app.db.models import metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m pipelines.api_data migrate with a local database connection")
context.configure(connection=connection, target_metadata=metadata)
with context.begin_transaction():
    context.run_migrations()
