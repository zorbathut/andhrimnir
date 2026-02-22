import asyncio

import aiosqlite

from andhrimnir.source.base import TemperatureSource

CREATE_READINGS = """\
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

CREATE_PROBE_NAMES = """\
CREATE TABLE IF NOT EXISTS probe_names (
    probe_num INTEGER PRIMARY KEY,
    name TEXT NOT NULL
)
"""

SEED_PROBE_NAMES = """\
INSERT OR IGNORE INTO probe_names (probe_num, name) VALUES (?, ?)
"""

INSERT = """\
INSERT INTO readings (timestamp, probe1, probe2, probe3, probe4, probe5, probe6)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute(CREATE_READINGS)
    await conn.execute(CREATE_PROBE_NAMES)
    for i in range(1, 7):
        await conn.execute(SEED_PROBE_NAMES, (i, f"Probe {i}"))
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


async def get_probe_names(conn: aiosqlite.Connection) -> dict[str, str]:
    cursor = await conn.execute("SELECT probe_num, name FROM probe_names ORDER BY probe_num")
    rows = await cursor.fetchall()
    return {str(row[0]): row[1] for row in rows}


async def set_probe_name(conn: aiosqlite.Connection, probe_num: int, name: str) -> None:
    await conn.execute(
        "UPDATE probe_names SET name = ? WHERE probe_num = ?", (name, probe_num)
    )
    await conn.commit()
