import argparse
import json
import getpass
from typing import Any, Dict, List, Tuple, Optional

import psycopg
from psycopg import sql


def pg_ident(name: str) -> str:
    out = []
    for c in name.strip():
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


def detect_pg_type(v: Any) -> str:
    if v is None:
        return "text"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int) and not isinstance(v, bool):
        return "bigint"
    if isinstance(v, float):
        return "double precision"
    if isinstance(v, (dict, list)):
        return "jsonb"
    return "text"


def unify_types(t1: str, t2: str) -> str:
    if t1 == t2:
        return t1
    if {t1, t2} <= {"bigint", "double precision"}:
        return "double precision"
    # keep it safe
    return "text"


def load_odata_value(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict) or "value" not in payload:
        raise ValueError("Expected top-level JSON object with a 'value' array (OData style).")

    rows = payload["value"]
    if not isinstance(rows, list):
        raise ValueError("'value' must be a list of objects.")

    cleaned: List[Dict[str, Any]] = []
    for obj in rows:
        if not isinstance(obj, dict):
            continue
        # drop @odata.* fields and normalize keys
        row = {pg_ident(k): v for k, v in obj.items() if not k.startswith("@")}
        cleaned.append(row)

    if not cleaned:
        raise ValueError("No usable rows found in payload['value'].")

    return cleaned


def infer_schema(rows: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    col_types: Dict[str, str] = {}
    for r in rows:
        for k, v in r.items():
            t = detect_pg_type(v)
            col_types[k] = unify_types(col_types[k], t) if k in col_types else t
    return sorted(col_types.items())


def ensure_table(conn, schema: str, table: str, columns: List[Tuple[str, str]]):
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

        col_defs = [
            sql.SQL("{} {}").format(sql.Identifier(col), sql.SQL(pg_type))
            for col, pg_type in columns
        ]
        col_defs.append(sql.SQL("{} {} DEFAULT now()").format(sql.Identifier("_ingested_at"), sql.SQL("timestamptz")))

        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} ({});").format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.SQL(", ").join(col_defs),
            )
        )
    conn.commit()


def copy_rows(conn, schema: str, table: str, columns: List[Tuple[str, str]], rows: List[Dict[str, Any]]):
    col_names = [c for c, _ in columns]

    copy_sql = sql.SQL(
        "COPY {}.{} ({}) FROM STDIN WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N');"
    ).format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, col_names)),
    )

    with conn.cursor() as cur, cur.copy(copy_sql) as cp:
        for r in rows:
            vals = []
            for c in col_names:
                v = r.get(c, None)
                if v is None:
                    vals.append("\\N")
                elif isinstance(v, (dict, list)):
                    vals.append(json.dumps(v, ensure_ascii=False).replace("\t", " ").replace("\n", " "))
                else:
                    vals.append(str(v).replace("\t", " ").replace("\n", " "))
            cp.write("\t".join(vals) + "\n")
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="Example: postgresql://user@host:5432/db  (password can be prompted)")
    ap.add_argument("--file", required=True, help="Path to JSON file containing { 'value': [ ... ] }")
    ap.add_argument("--schema", default="public")
    ap.add_argument("--table", required=True)
    ap.add_argument("--prompt-password", action="store_true", help="Prompt for password instead of putting in DSN")
    args = ap.parse_args()

    rows = load_odata_value(args.file)
    columns = infer_schema(rows)

    dsn = args.dsn
    if args.prompt_password:
        pwd = getpass.getpass("Postgres password: ")
        # psycopg supports keyword DSN params appended like this
        dsn = dsn + f" password={pwd}"

    with psycopg.connect(dsn) as conn:
        ensure_table(conn, args.schema, args.table, columns)
        copy_rows(conn, args.schema, args.table, columns, rows)

    print(f"Inserted {len(rows)} rows into {args.schema}.{args.table}")


if __name__ == "__main__":
    main()
