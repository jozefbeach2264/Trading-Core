import os
from psycopg_pool import ConnectionPool

DDL_PATH = os.environ.get("PG_DDL_PATH", "migrations/pg_schema.sql")
dsn = os.environ["POSTGRES_DSN"]

ddl = open(DDL_PATH, "r").read()
pool = ConnectionPool(dsn, min_size=1, max_size=1, kwargs={"autocommit": True})

with pool.connection() as c, c.cursor() as cur:
    for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
        cur.execute(stmt + ";")

print("Schema applied.")