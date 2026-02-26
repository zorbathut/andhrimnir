import aiosqlite


async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute("""\
CREATE TABLE IF NOT EXISTS alert_thresholds (
    probe_num INTEGER PRIMARY KEY,
    low_temp_f REAL,
    high_temp_f REAL
)
""")
    for i in range(1, 7):
        await conn.execute(
            "INSERT OR IGNORE INTO alert_thresholds (probe_num, low_temp_f, high_temp_f) VALUES (?, NULL, NULL)",
            (i,),
        )
