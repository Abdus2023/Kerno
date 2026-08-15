"""
Built-in SQL skills.

Works with any SQLAlchemy-supported database.
Designed for the common pattern: query → DataFrame → analyze.
"""

_SQL_SKILLS_CODE = '''
import pandas as pd
from IPython.display import display as _display, HTML as _HTML


# ── Connection management ──────────────────────────────────────────────────────

_SQL_CONNECTIONS = {}   # alias → engine


def connect(
    connection_string: str,
    alias: str = "default",
) -> object:
    """
    Connect to a database and register it for use in query().

    Supported connection strings:
      SQLite:     "sqlite:///path/to/file.db"
      PostgreSQL: "postgresql://user:pass@host:port/dbname"
      MySQL:      "mysql+pymysql://user:pass@host:port/dbname"
      DuckDB:     "duckdb:///path/to/file.duckdb"

    Args:
        connection_string: SQLAlchemy connection string
        alias:             Short name for subsequent queries (default: "default")

    Returns:
        SQLAlchemy engine
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(connection_string, future=True)

    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    _SQL_CONNECTIONS[alias] = engine
    print(f"✓ Connected to '{alias}': {connection_string.split('@')[-1]}")
    return engine


def connect_sqlite(path: str, alias: str = "default") -> object:
    """
    Convenience: connect to a SQLite file or in-memory database.

    Args:
        path:  File path, or ":memory:" for in-memory
        alias: Connection alias
    """
    return connect(f"sqlite:///{path}", alias=alias)


def query(
    sql:   str,
    alias: str = "default",
    limit: int = 10_000,
) -> pd.DataFrame:
    """
    Execute a SQL query and return results as a DataFrame.

    Args:
        sql:   SQL query string
        alias: Connection alias (from connect())
        limit: Maximum rows to return (safety limit)

    Returns:
        DataFrame with query results

    Example:
        df = query("SELECT region, SUM(revenue) FROM sales GROUP BY region")
    """
    from sqlalchemy import text

    engine = _SQL_CONNECTIONS.get(alias)
    if engine is None:
        available = list(_SQL_CONNECTIONS.keys())
        raise RuntimeError(
            f"No connection '{alias}'. "
            f"Available: {available}. "
            f"Call connect() first."
        )

    # Inject limit if not present
    sql_upper = sql.strip().upper()
    if sql_upper.startswith("SELECT") and "LIMIT" not in sql_upper:
        safe_sql = f"{sql.rstrip(';')} LIMIT {limit}"
    else:
        safe_sql = sql

    with engine.connect() as conn:
        df = pd.read_sql(text(safe_sql), conn)

    print(f"✓ Query returned {df.shape[0]:,} rows × {df.shape[1]} cols")
    _display(df.head(5))
    return df


def list_tables(alias: str = "default") -> list:
    """
    List all tables in the connected database.

    Returns:
        list of table names
    """
    from sqlalchemy import inspect as _inspect

    engine = _SQL_CONNECTIONS.get(alias)
    if engine is None:
        raise RuntimeError(f"No connection '{alias}'. Call connect() first.")

    inspector  = _inspect(engine)
    tables     = inspector.get_table_names()
    views      = inspector.get_view_names()

    print(f"Tables ({len(tables)}):")
    for t in tables:
        print(f"  {t}")

    if views:
        print(f"Views ({len(views)}):")
        for v in views:
            print(f"  {v}")

    return tables


def schema_of_table(table_name: str, alias: str = "default") -> pd.DataFrame:
    """
    Show the schema (columns, types, nullable) of a table.

    Returns:
        DataFrame with columns: name, type, nullable, default
    """
    from sqlalchemy import inspect as _inspect

    engine = _SQL_CONNECTIONS.get(alias)
    if engine is None:
        raise RuntimeError(f"No connection '{alias}'. Call connect() first.")

    inspector = _inspect(engine)
    columns   = inspector.get_columns(table_name)

    schema_df = pd.DataFrame([
        {
            "name":     col["name"],
            "type":     str(col["type"]),
            "nullable": col.get("nullable", True),
            "default":  str(col.get("default", "")),
        }
        for col in columns
    ])

    print(f"Schema of '{table_name}' ({len(schema_df)} columns):")
    _display(schema_df)
    return schema_df


def execute_sql(sql: str, alias: str = "default") -> None:
    """
    Execute a non-SELECT statement (CREATE, INSERT, UPDATE, DROP).
    No return value — for DDL and DML operations.

    Args:
        sql:   SQL statement
        alias: Connection alias
    """
    from sqlalchemy import text

    engine = _SQL_CONNECTIONS.get(alias)
    if engine is None:
        raise RuntimeError(f"No connection '{alias}'. Call connect() first.")

    with engine.begin() as conn:
        conn.execute(text(sql))

    print(f"✓ Executed: {sql[:80]}...")


def table_stats(table_name: str, alias: str = "default") -> dict:
    """
    Quick statistics for a table: row count, column count, sample rows.

    Returns:
        dict: {row_count, col_count, schema, sample}
    """
    df  = query(f"SELECT * FROM {table_name}", alias=alias, limit=5)
    cnt = query(f"SELECT COUNT(*) as n FROM {table_name}", alias=alias)

    stats = {
        "table":     table_name,
        "row_count": int(cnt["n"].iloc[0]),
        "col_count": len(df.columns),
        "columns":   list(df.columns),
        "sample":    df.to_dict(orient="records"),
    }

    print(f"Table '{table_name}': {stats['row_count']:,} rows × {stats['col_count']} cols")
    return stats
'''


def get_code() -> str:
    return _SQL_SKILLS_CODE
