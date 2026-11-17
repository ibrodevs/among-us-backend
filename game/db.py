"""Dedicated PostgreSQL sessions inherit the same TLS policy as Django."""

import os
import psycopg
from django.conf import settings


def dedicated_connection():
    options = settings.DATABASES["default"].get("OPTIONS", {})
    tls = {
        key: options[key]
        for key in ["sslmode", "sslrootcert", "sslcert", "sslkey"]
        if key in options
    }
    return psycopg.connect(
        os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5, **tls
    )
