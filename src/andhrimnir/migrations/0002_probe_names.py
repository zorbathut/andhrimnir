import aiosqlite


async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute("""\
CREATE TABLE IF NOT EXISTS probe_names (
    probe_num INTEGER PRIMARY KEY,
    name TEXT NOT NULL
)
""")
    for i in range(1, 7):
        await conn.execute(
            "INSERT OR IGNORE INTO probe_names (probe_num, name) VALUES (?, ?)",
            (i, f"Probe {i}"),
        )
