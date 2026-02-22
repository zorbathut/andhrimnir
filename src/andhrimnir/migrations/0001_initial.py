import aiosqlite


async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute("""\
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
""")
