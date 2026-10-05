import psycopg


class PostgresHealth:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def ping(self) -> bool:
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False
