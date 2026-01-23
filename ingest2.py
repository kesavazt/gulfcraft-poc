import argparse
import json
import getpass
from typing import Any, Dict, List, Tuple

import psycopg
from psycopg import sql


def clean_value(v: Any) -> Any:
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def pg_ident(name: str) -> str:
    out = []
    for c in str(name).strip():
        if c.isalnum() or c == "_":
            out.append(c.lower())
        elif c in (" ", "-", "."):
            out.append("_")
        else:
            out.append("_")
    s = "".join(out)
    if not s or s[0].isdigit():
        s = f"c_{s}"
    while "__" in s:
        s = s.replace("__", "_")
    return s[:63]


def load_odata_value(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "value" not in payload or not isinstance(payload["value"], list):
        raise ValueError("Expected JSON shape: { 'value': [ ... ] }")
    return payload["value"]


def infer_top_level_columns(rows: List[Dict[str, Any]]) -> List[str]:
    cols = set()
    for obj in rows:
        if not isinstance(obj, dict):
            continue
        for k in obj.keys():
            if str(k).startswith("@"):
                continue
            if k == "ReleasedProducts":
                continue
            cols.add(pg_ident(k))
    return sorted(cols)


def infer_released_columns(rows: List[Dict[str, Any]]) -> List[str]:
    cols = set()
    for obj in rows:
        if not isinstance(obj, dict):
            continue
        rp = obj.get("ReleasedProducts")
        if not isinstance(rp, list):
            continue
        for item in rp:
            if not isinstance(item, dict):
                continue
            for k in item.keys():
                if str(k).startswith("@"):
                    continue
                cols.add(pg_ident(k))
    return sorted(cols)


def max_released_len(rows: List[Dict[str, Any]]) -> int:
    m = 0
    for obj in rows:
        rp = obj.get("ReleasedProducts")
        if isinstance(rp, list):
            m = max(m, len(rp))
    return m


def pg_type_for_col(col: str) -> str:
    # simple rules: numbers for known numeric fields, else text
    # Extend this mapping if you have more numeric fields
    if col in {"unitcost"}:
        return "double precision"
    return "text"


def ensure_table(conn, schema: str, table: str, top_cols: List[str], rp_cols: List[str], rp_max: int):
    all_cols: List[Tuple[str, str]] = []

    # top-level
    for c in top_cols:
        # Make ProductNumber NOT NULL if present
        if c == "productnumber":
            all_cols.append((c, "text NOT NULL"))
        else:
            all_cols.append((c, "text"))

    # released products expanded: colname + index suffix
    for i in range(1, rp_max + 1):
        for base in rp_cols:
            col_name = f"{base}{i}"
            all_cols.append((col_name, pg_type_for_col(base)))

    # metadata
    all_cols.append(("_ingested_at", "timestamptz DEFAULT now()"))

    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({});").format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.SQL(", ").join(
                    sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in all_cols
                ),
            )
        )

        # Optional index on productnumber
        if "productnumber" in top_cols:
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} (productnumber);").format(
                    sql.Identifier(f"idx_{table}_productnumber"),
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )

    conn.commit()


def build_flat_rows(rows: List[Dict[str, Any]], top_cols: List[str], rp_cols: List[str], rp_max: int) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []

    for obj in rows:
        if not isinstance(obj, dict):
            continue

        # top-level (drop @ and ReleasedProducts)
        top = {}
        for k, v in obj.items():
            if str(k).startswith("@") or k == "ReleasedProducts":
                continue
            top[pg_ident(k)] = clean_value(v)

        rp = obj.get("ReleasedProducts")
        rp_list = rp if isinstance(rp, list) else []

        # start row with top-level columns
        row: Dict[str, Any] = {c: top.get(c) for c in top_cols}

        # fill expanded released columns
        for i in range(1, rp_max + 1):
            item = rp_list[i - 1] if (i - 1) < len(rp_list) and isinstance(rp_list[i - 1], dict) else None
            cleaned_item = {}
            if item:
                cleaned_item = {pg_ident(k): clean_value(v) for k, v in item.items() if not str(k).startswith("@")}

            for base in rp_cols:
                row[f"{base}{i}"] = cleaned_item.get(base)

        flat.append(row)

    return flat


def copy_rows(conn, schema: str, table: str, columns: List[str], rows: List[Dict[str, Any]]):
    copy_sql = sql.SQL(
        "COPY {}.{} ({}) FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N');"
    ).format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )

    def safe_str(x: str) -> str:
        return x.replace("\t", " ").replace("\n", " ")

    with conn.cursor() as cur, cur.copy(copy_sql) as cp:
        for r in rows:
            vals: List[str] = []
            for c in columns:
                v = r.get(c)
                if v is None:
                    vals.append("\\N")
                else:
                    vals.append(safe_str(str(v)))
            cp.write("\t".join(vals) + "\n")

    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="postgresql://user@host:5432/db (use --prompt-password or include :pass)")
    ap.add_argument("--file", required=True)
    ap.add_argument("--schema", default="public")
    ap.add_argument("--table", required=True)
    ap.add_argument("--prompt-password", action="store_true")
    args = ap.parse_args()

    dsn = args.dsn
    if args.prompt_password:
        pwd = getpass.getpass("Postgres password: ")
        dsn = dsn + f" password={pwd}"

    rows = load_odata_value(args.file)

    top_cols = infer_top_level_columns(rows)
    rp_cols = infer_released_columns(rows)
    rp_max = max_released_len(rows)

    # Make sure ProductNumber is included even if inference misses due to case
    if "productnumber" not in top_cols:
        top_cols = ["productnumber"] + top_cols

    # You specifically care about ItemNumber + UnitCost; keep them even if inference misses
    for must in ("itemnumber", "unitcost"):
        if must not in rp_cols:
            rp_cols.append(must)
    rp_cols = sorted(set(rp_cols))

    flat_rows = build_flat_rows(rows, top_cols, rp_cols, rp_max)

    # Final column order
    all_columns: List[str] = []
    all_columns.extend(top_cols)
    for i in range(1, rp_max + 1):
        for base in rp_cols:
            all_columns.append(f"{base}{i}")

    with psycopg.connect(dsn) as conn:
        ensure_table(conn, args.schema, args.table, top_cols, rp_cols, rp_max)
        copy_rows(conn, args.schema, args.table, all_columns, flat_rows)

    print(f"Inserted {len(flat_rows)} rows into {args.schema}.{args.table}")
    print(f"ReleasedProducts max count detected: {rp_max}")
    print(f"Expanded released columns: {', '.join(rp_cols)}")


if __name__ == "__main__":
    main()
