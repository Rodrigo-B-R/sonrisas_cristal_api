"""python -m scripts.create_tables [path/to/01-init.sql]

Runs ../sonrisas_cristal_db/init/01-init.sql if the database is empty. Use it with Render or any
database that was not created by the sonrisas_cristal_db docker-compose. With that compose the
tables already exist and there is nothing to do.

DATABASE_URL must belong to the database owner (for example postgres), not to api_user:
api_user is not allowed to create tables.
"""

import sys
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from app.config import settings

DEFAULT_SQL = Path(__file__).resolve().parents[2] / "sonrisas_cristal_db" / "init" / "01-init.sql"


def main() -> int:
    sql_file = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_SQL
    if not sql_file.exists():
        print(f"I could not find the SQL script at {sql_file}")
        print("Pass it like this: python -m scripts.create_tables C:\\path\\to\\01-init.sql")
        return 1

    # psycopg wants a plain "postgresql://" URL, without SQLAlchemy's "+psycopg"
    url = make_url(settings.database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url) as connection:
        exists = connection.execute("SELECT to_regclass('public.usuario')").fetchone()[0]
        if exists:
            print("The tables already exist: I did nothing. Next: python -m scripts.seed")
            return 0
        print(f"Running {sql_file} ...")
        connection.execute(sql_file.read_text(encoding="utf-8"))  # one transaction: all or nothing
        connection.commit()
        count = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchone()[0]
        print(f"Done: {count} tables created. Next: python -m scripts.seed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
