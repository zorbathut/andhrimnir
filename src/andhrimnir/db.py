import asyncio
import importlib
import logging
from pathlib import Path

import aiosqlite

from andhrimnir.source.base import TemperatureSource

log = logging.getLogger(__name__)

INSERT = """\
INSERT INTO readings (timestamp, probe1, probe2, probe3, probe4, probe5, probe6)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def init_db(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    await conn.commit()

    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    current = row[0] or 0

    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9]*.py"))
    for path in migration_files:
        version = int(path.stem.split("_", 1)[0])
        if version <= current:
            continue
        module = importlib.import_module(f"andhrimnir.migrations.{path.stem}")
        await module.migrate(conn)
        await conn.execute("INSERT INTO schema_version VALUES (?)", (version,))
        await conn.commit()
        log.info("Applied migration %04d (%s)", version, path.stem)

    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    log.info("Database schema version: %d", row[0] or 0)

    return conn


async def db_writer(source: TemperatureSource, conn: aiosqlite.Connection) -> None:
    queue = source.subscribe()
    try:
        while True:
            reading = await queue.get()
            await conn.execute(
                INSERT,
                (
                    reading.timestamp.isoformat(),
                    reading.probe1,
                    reading.probe2,
                    reading.probe3,
                    reading.probe4,
                    reading.probe5,
                    reading.probe6,
                ),
            )
            await conn.commit()
    except asyncio.CancelledError:
        pass
    finally:
        source.unsubscribe(queue)


async def get_history(
    conn: aiosqlite.Connection, limit: int = 100, since: str | None = None
) -> list[dict]:
    query = (
        "SELECT timestamp, probe1, probe2, probe3, probe4, probe5, probe6 "
        "FROM readings"
    )
    params: list = []
    if since:
        query += " WHERE timestamp >= ?"
        params.append(since)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor = await conn.execute(query, params)
    rows = await cursor.fetchall()
    return [
        {
            "timestamp": row[0],
            "probes": {
                "1": row[1],
                "2": row[2],
                "3": row[3],
                "4": row[4],
                "5": row[5],
                "6": row[6],
            },
        }
        for row in rows
    ]


async def get_probe_names(conn: aiosqlite.Connection) -> dict[str, str]:
    cursor = await conn.execute("SELECT probe_num, name FROM probe_names ORDER BY probe_num")
    rows = await cursor.fetchall()
    return {str(row[0]): row[1] for row in rows}


async def set_probe_name(conn: aiosqlite.Connection, probe_num: int, name: str) -> None:
    await conn.execute(
        "UPDATE probe_names SET name = ? WHERE probe_num = ?", (name, probe_num)
    )
    await conn.commit()
