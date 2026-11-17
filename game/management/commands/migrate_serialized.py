"""Run exactly one controlled schema migration job at a time."""

from game.db import dedicated_connection
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run migrations under a dedicated PostgreSQL session advisory lock"

    def handle(self, *args, **options):
        with dedicated_connection() as conn:
            conn.execute("SELECT pg_advisory_lock(%s)", (0x435245574D494752,))
            try:
                call_command("migrate", interactive=False)
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (0x435245574D494752,))
