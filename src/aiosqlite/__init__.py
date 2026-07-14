from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from typing import Any, Self, cast

DatabaseError = sqlite3.DatabaseError
Error = sqlite3.Error
IntegrityError = sqlite3.IntegrityError
NotSupportedError = sqlite3.NotSupportedError
OperationalError = sqlite3.OperationalError
ProgrammingError = sqlite3.ProgrammingError
sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info


class _ImmediateQueue:
    def put_nowait(self, item: tuple[asyncio.Future[Any], Any]) -> None:
        future, function = item
        try:
            future.set_result(function())
        except Exception as exc:  # pragma: no cover
            future.set_exception(exc)


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    async def execute(self, sql: str, parameters: Any = None) -> Self:
        if parameters is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, parameters)
        return self

    async def executemany(self, sql: str, seq_of_parameters: Iterable[Any]) -> Self:
        self._cursor.executemany(sql, seq_of_parameters)
        return self

    async def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    async def fetchone(self) -> Any | None:
        return self._cursor.fetchone()

    async def close(self) -> None:
        self._cursor.close()


class Connection:
    def __init__(self, database: str, **kwargs: Any) -> None:
        kwargs.setdefault("check_same_thread", False)
        self._conn = sqlite3.connect(database, **kwargs)
        self._tx = _ImmediateQueue()
        self._thread = self

    @property
    def daemon(self) -> bool:
        return True

    @daemon.setter
    def daemon(self, value: bool) -> None:
        return None

    @property
    def isolation_level(self) -> str | None:
        return cast(str | None, self._conn.isolation_level)

    @isolation_level.setter
    def isolation_level(self, value: str | None) -> None:
        self._conn.isolation_level = value

    def __await__(self) -> Any:
        async def _ready() -> Connection:
            return self

        return _ready().__await__()

    async def cursor(self) -> Cursor:
        return Cursor(self._conn.cursor())

    async def execute(self, sql: str, parameters: Any = None) -> Cursor:
        cursor = await self.cursor()
        await cursor.execute(sql, parameters)
        return cursor

    async def create_function(self, *args: Any, **kwargs: Any) -> None:
        self._conn.create_function(*args, **kwargs)

    async def rollback(self) -> None:
        self._conn.rollback()

    async def commit(self) -> None:
        self._conn.commit()

    async def close(self) -> None:
        self._conn.close()

    def stop(self) -> None:
        self._conn.close()


def connect(database: str, **kwargs: Any) -> Connection:
    return Connection(database, **kwargs)
