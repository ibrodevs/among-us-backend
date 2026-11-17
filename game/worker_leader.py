"""One durable clock leader, with a dedicated PostgreSQL session lock.
Use a direct or SESSION-pooler endpoint, never transaction pooling.
"""

import psycopg
from game.db import dedicated_connection

KEY = 0x435245574D415445


class ClockLeader:
    def __init__(self):
        self.conn = None
        self.held = False

    def acquire(self):
        try:
            if self.conn is None or self.conn.closed:
                self.held = False
                self.conn = dedicated_connection()
            if self.held:
                self.conn.execute("SELECT 1")
                return True
            self.held = self.conn.execute(
                "SELECT pg_try_advisory_lock(%s)", (KEY,)
            ).fetchone()[0]
            return self.held
        except (psycopg.Error, OSError):
            self.close()
            return False

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            self.held = False
