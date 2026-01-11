from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator

import pytest

import sqlite3

from brain_api.app import db


@contextmanager
def _open_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    gen: Generator[sqlite3.Connection, None, None] = db.get_connection(db_path)
    conn = next(gen)
    try:
        yield conn
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


@pytest.fixture()
def db_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "test.db"
    db.init_db(str(db_path))
    with _open_connection(str(db_path)) as conn:
        yield conn
