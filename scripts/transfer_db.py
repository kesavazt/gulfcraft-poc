"""
Database Transfer Script
========================
Transfers all data from a source Azure PostgreSQL database to a destination
PostgreSQL database (can be on a different Azure tenant or any Postgres host).

Usage:
    python scripts/transfer_db.py

    Configure via environment variables or .env file:
        SOURCE_DATABASE_URL  - Connection string for the source DB
        DEST_DATABASE_URL    - Connection string for the destination DB

    Or pass as CLI arguments:
        python scripts/transfer_db.py \
            --source "postgresql+psycopg2://user:pass@source-host:5432/dbname" \
            --dest   "postgresql+psycopg2://user:pass@dest-host:5432/dbname"

Options:
        --drop-existing      Drop existing tables on destination before transfer
        --tables TABLE1,TABLE2  Only transfer specific tables (comma-separated)
        --batch-size N       Number of rows per insert batch (default: 1000)
        --dry-run            Show what would be transferred without writing
"""

import argparse
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text, MetaData
from sqlalchemy.orm import sessionmaker
from pgvector.sqlalchemy import Vector  # Registers the Vector type for reflection

# Add parent directory to path so we can import the models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# Tables in dependency order (parents before children)
TABLE_ORDER = [
    "users",
    "products",
    "quotation_lines",
    "estimation_lines",
    "conversations",
    "messages",
    "costing_requests",
    "costing_line_items",
    "pending_quote_requests",
]


def get_engines(source_url: str, dest_url: str):
    """Create SQLAlchemy engines for source and destination databases."""
    source_engine = create_engine(source_url, echo=False)
    dest_engine = create_engine(dest_url, echo=False)
    return source_engine, dest_engine


def test_connections(source_engine, dest_engine):
    """Verify both database connections work."""
    print("[1/5] Testing connections...")
    try:
        with source_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"  Source DB connected: {version[:60]}...")
    except Exception as e:
        print(f"  ERROR: Cannot connect to source DB: {e}")
        sys.exit(1)

    try:
        with dest_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"  Dest DB connected:   {version[:60]}...")
    except Exception as e:
        print(f"  ERROR: Cannot connect to destination DB: {e}")
        sys.exit(1)


def setup_extensions(dest_engine):
    """Ensure required extensions exist on the destination database."""
    print("[2/5] Setting up extensions on destination...")
    with dest_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        print("  pgvector extension ready.")


def setup_schema(source_engine, dest_engine, drop_existing: bool):
    """Recreate the schema on the destination database using SQLAlchemy models."""
    print("[3/5] Setting up schema on destination...")

    # Reflect the source schema
    metadata = MetaData()
    metadata.reflect(bind=source_engine)

    if drop_existing:
        print("  Dropping existing tables on destination...")
        metadata.drop_all(bind=dest_engine)

    metadata.create_all(bind=dest_engine)
    print(f"  Schema ready ({len(metadata.tables)} tables).")
    return metadata


def transfer_data(
    source_engine,
    dest_engine,
    metadata: MetaData,
    tables_filter: list[str] | None,
    batch_size: int,
    dry_run: bool,
):
    """Transfer data from source to destination table by table."""
    print("[4/5] Transferring data...")

    source_inspector = inspect(source_engine)
    source_tables = set(source_inspector.get_table_names())

    # Determine which tables to transfer and in what order
    tables_to_transfer = [t for t in TABLE_ORDER if t in source_tables]
    # Add any tables not in TABLE_ORDER (catch-all)
    for t in source_tables:
        if t not in tables_to_transfer:
            tables_to_transfer.append(t)

    if tables_filter:
        tables_to_transfer = [t for t in tables_to_transfer if t in tables_filter]

    total_rows = 0
    transfer_stats = []

    for table_name in tables_to_transfer:
        if table_name not in metadata.tables:
            print(f"  SKIP: {table_name} (not in reflected schema)")
            continue

        table = metadata.tables[table_name]

        # Count rows in source
        with source_engine.connect() as conn:
            count = conn.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            ).scalar()

        if count == 0:
            print(f"  {table_name}: 0 rows (skipping)")
            transfer_stats.append((table_name, 0, 0))
            continue

        if dry_run:
            print(f"  {table_name}: {count} rows (dry run - skipped)")
            transfer_stats.append((table_name, count, 0))
            total_rows += count
            continue

        start_time = time.time()
        print(f"  {table_name}: {count} rows ", end="", flush=True)

        # Truncate destination table before inserting (CASCADE to handle FK refs)
        with dest_engine.connect() as conn:
            conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
            conn.commit()

        # Get column names, excluding computed/generated columns (like tsv)
        dest_inspector = inspect(dest_engine)
        dest_columns = dest_inspector.get_columns(table_name)
        computed_cols = {
            col["name"]
            for col in dest_columns
            if col.get("computed") or col.get("identity")
        }

        # Also detect server-generated tsvector columns from the source
        source_columns = source_inspector.get_columns(table_name)
        for col in source_columns:
            if str(col.get("type", "")).upper() == "TSVECTOR":
                computed_cols.add(col["name"])
            if col.get("computed"):
                computed_cols.add(col["name"])

        # Build column list excluding computed columns
        column_names = [c.name for c in table.columns if c.name not in computed_cols]

        # Read and insert in batches
        rows_transferred = 0
        with source_engine.connect() as src_conn:
            col_list = ", ".join(f'"{c}"' for c in column_names)
            result = src_conn.execution_options(stream_results=True).execute(
                text(f'SELECT {col_list} FROM "{table_name}" ORDER BY 1')
            )

            batch = []
            for row in result:
                batch.append(dict(zip(column_names, row)))
                if len(batch) >= batch_size:
                    _insert_batch(dest_engine, table_name, column_names, batch)
                    rows_transferred += len(batch)
                    batch = []
                    print(".", end="", flush=True)

            if batch:
                _insert_batch(dest_engine, table_name, column_names, batch)
                rows_transferred += len(batch)

        elapsed = time.time() - start_time
        print(f" done ({elapsed:.1f}s)")
        transfer_stats.append((table_name, count, elapsed))
        total_rows += rows_transferred

    return transfer_stats, total_rows


def _insert_batch(engine, table_name, column_names, batch: list[dict]):
    """Insert a batch of rows using raw SQL to bypass type processors (pgvector issue)."""
    col_list = ", ".join(f'"{c}"' for c in column_names)
    placeholders = ", ".join(f":{c}" for c in column_names)
    sql = text(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})')

    # Convert any non-primitive values to strings for raw SQL passthrough
    cleaned_batch = []
    for row in batch:
        cleaned = {}
        for k, v in row.items():
            if v is not None and not isinstance(v, (str, int, float, bool, datetime)):
                cleaned[k] = str(v)
            else:
                cleaned[k] = v
        cleaned_batch.append(cleaned)

    with engine.connect() as conn:
        conn.execute(sql, cleaned_batch)
        conn.commit()


def reset_sequences(dest_engine):
    """Reset auto-increment sequences on destination to match transferred data."""
    print("[5/5] Resetting sequences...")
    with dest_engine.connect() as conn:
        # Only reset sequences for our known tables
        for table_name in TABLE_ORDER:
            try:
                # Find serial/identity columns for this table
                result = conn.execute(text("""
                    SELECT a.attname, pg_get_serial_sequence(:tbl, a.attname::text)
                    FROM pg_attribute a
                    JOIN pg_class t ON a.attrelid = t.oid
                    WHERE t.relname = :tbl
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                      AND pg_get_serial_sequence(:tbl, a.attname::text) IS NOT NULL
                """), {"tbl": table_name})

                for col_name, seq_name in result:
                    conn.execute(text(
                        f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(\"{col_name}\") FROM \"{table_name}\"), 1))"
                    ))
                    print(f"  Reset {seq_name}")
            except Exception:
                pass  # Table may not exist on destination

        conn.commit()
    print("  Sequences reset.")


def print_summary(stats, total_rows, elapsed):
    """Print a summary of the transfer."""
    print("\n" + "=" * 55)
    print("Transfer Summary")
    print("=" * 55)
    print(f"{'Table':<28} {'Rows':>8} {'Time':>8}")
    print("-" * 55)
    for table_name, count, t in stats:
        time_str = f"{t:.1f}s" if t > 0 else "-"
        print(f"  {table_name:<26} {count:>8} {time_str:>8}")
    print("-" * 55)
    print(f"  {'TOTAL':<26} {total_rows:>8} {elapsed:.1f}s")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="Transfer Azure PostgreSQL data to another PostgreSQL instance")
    parser.add_argument("--source", help="Source database URL (or set SOURCE_DATABASE_URL env var)")
    parser.add_argument("--dest", help="Destination database URL (or set DEST_DATABASE_URL env var)")
    parser.add_argument("--drop-existing", action="store_true", help="Drop existing tables on destination first")
    parser.add_argument("--tables", help="Comma-separated list of tables to transfer")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per insert batch (default: 1000)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be transferred without writing")
    args = parser.parse_args()

    source_url = args.source or os.getenv("SOURCE_DATABASE_URL")
    dest_url = args.dest or os.getenv("DEST_DATABASE_URL")

    if not source_url:
        # Fall back to the app's DATABASE_URL as the source
        source_url = os.getenv("DATABASE_URL")
    if not source_url:
        print("ERROR: No source database URL. Set SOURCE_DATABASE_URL or use --source")
        sys.exit(1)
    if not dest_url:
        print("ERROR: No destination database URL. Set DEST_DATABASE_URL or use --dest")
        sys.exit(1)

    # Sanitize URLs for display (hide passwords)
    def mask_url(url: str) -> str:
        if "@" in url and ":" in url.split("@")[0]:
            prefix, rest = url.rsplit("@", 1)
            parts = prefix.rsplit(":", 1)
            return parts[0] + ":****@" + rest
        return url

    print(f"\nSource: {mask_url(source_url)}")
    print(f"Dest:   {mask_url(dest_url)}")
    if args.dry_run:
        print("MODE:   DRY RUN (no data will be written)\n")
    else:
        print()

    tables_filter = [t.strip() for t in args.tables.split(",")] if args.tables else None

    source_engine, dest_engine = get_engines(source_url, dest_url)

    overall_start = time.time()

    test_connections(source_engine, dest_engine)
    setup_extensions(dest_engine)
    metadata = setup_schema(source_engine, dest_engine, args.drop_existing)
    stats, total_rows = transfer_data(
        source_engine, dest_engine, metadata, tables_filter, args.batch_size, args.dry_run
    )
    if not args.dry_run:
        reset_sequences(dest_engine)

    elapsed = time.time() - overall_start
    print_summary(stats, total_rows, elapsed)

    source_engine.dispose()
    dest_engine.dispose()


if __name__ == "__main__":
    main()
