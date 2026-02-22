import asyncio

import aiosqlite

from andhrimnir.source.base import TemperatureSource

CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    probe1 REAL,
    probe2 REAL,
    probe3 REAL,
    probe4 REAL,
    probe5 REAL,
    probe6 REAL
)
"""

INSERT = """\
INSERT INTO readings (timestamp, probe1, probe2, probe3, probe4, probe5, probe6)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute(CREATE_TABLE)
    await conn.commit()
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
