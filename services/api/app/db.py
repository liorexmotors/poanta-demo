from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("POANTA_DATABASE_URL")


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


def db_available() -> bool:
    return bool(database_url())
