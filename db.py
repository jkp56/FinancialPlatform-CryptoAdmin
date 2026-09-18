import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from decimal import Decimal

sqlite3.register_converter("DECIMAL_TEXT", lambda value: Decimal(value.decode()))

DB_PATH = Path(
    os.environ.get(
        "CRYPTO_ADMIN_DB_PATH",
        Path(__file__).with_name("crypto_admin.sqlite3"),
    )
)
DEFAULT_ASSETS = (
    ("BTC", "Bitcoin", "XBTEUR", "57121.85", 10),
    ("ETH", "Ethereum", "ETHEUR", "3000.00", 20),
)
SEED = [
    ("2026-07-03", "BTC", "Storting", "Externe BTC-overboeking", .0086, 0, 0, 467.97),
    ("2026-07-03", "EUR", "EUR Storting", "Fiatstorting", 0, 50, 0, 0),
    ("2026-07-03", "BTC", "Inkoop", "Eenmalige aankoop", .0009, 50, 0, 0),
    ("2026-07-04", "EUR", "EUR Storting", "Fiatstorting", 0, 50, 0, 0),
    ("2026-07-06", "BTC", "Inkoop", "Periodieke aankoop", .00089, 50, 0, 0),
    ("2026-07-09", "BTC", "Reward", "Ontvangen beloning", .00000016, 0, 0, 0),
    ("2026-07-12", "EUR", "EUR Storting", "Fiatstorting", 0, 50, 0, 0),
    ("2026-07-13", "BTC", "Inkoop", "Periodieke aankoop", .00087, 50, 0, 0),
    ("2026-07-13", "BTC", "Storting", "Externe BTC-overboeking", .00194, 0, 0, 105.48),
    ("2026-07-15", "BTC", "Verkoop", "Verkoop", .00045, 25, 0, 0),
]


def connect():
    con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    return con


def _backup_legacy_database():
    if not DB_PATH.exists():
        return
    with closing(connect()) as con:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'"
        ).fetchone()
        if not table:
            return
        columns = {row["name"] for row in con.execute("PRAGMA table_info(transactions)")}
    if "asset" not in columns or "asset_amount" not in columns:
        backup = DB_PATH.with_name("crypto_admin.pre_multi_asset.sqlite3")
        if not backup.exists():
            shutil.copy2(DB_PATH, backup)


DECIMAL_COLUMNS = {"asset_amount", "eur_gross", "fee_eur", "transferred_cost_basis_eur", "manual_price"}


def _decimal_values(values):
    return {key: format(Decimal(str(value)), "f") if key in DECIMAL_COLUMNS else value
            for key, value in values.items()}


def _migrate_decimal_storage(con):
    tables = []
    for table in ("transactions", "assets"):
        columns = con.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] in DECIMAL_COLUMNS and row["type"] != "DECIMAL_TEXT" for row in columns):
            tables.append((table, columns))
    if not tables:
        return
    backup = DB_PATH.with_name(DB_PATH.stem + ".pre_decimal.sqlite3")
    if not backup.exists():
        with closing(sqlite3.connect(DB_PATH)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
    for table, columns in tables:
        rows = [dict(row) for row in con.execute(f"SELECT * FROM {table}")]
        definitions = []
        for column in columns:
            name = column["name"]
            definition = f'"{name}" ' + ("DECIMAL_TEXT" if name in DECIMAL_COLUMNS else column["type"])
            if column["pk"]:
                definition += " PRIMARY KEY"
            if column["notnull"]:
                definition += " NOT NULL"
            if column["dflt_value"] is not None:
                definition += " DEFAULT " + column["dflt_value"]
            definitions.append(definition)
        con.execute(f"CREATE TABLE {table}_decimal (" + ",".join(definitions) + ")")
        names = [column["name"] for column in columns]
        con.executemany(
            f"INSERT INTO {table}_decimal (" + ",".join(names) + ") VALUES (" + ",".join("?" for _ in names) + ")",
            [tuple(_decimal_values(row)[name] for name in names) for row in rows],
        )
        con.execute(f"DROP TABLE {table}")
        con.execute(f"ALTER TABLE {table}_decimal RENAME TO {table}")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _backup_legacy_database()
    with closing(connect()) as con, con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions(
              id INTEGER PRIMARY KEY,
              tx_date TEXT NOT NULL,
              asset TEXT NOT NULL DEFAULT 'BTC',
              type TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              asset_amount DECIMAL_TEXT NOT NULL DEFAULT '0',
              eur_gross DECIMAL_TEXT NOT NULL DEFAULT '0',
              fee_eur DECIMAL_TEXT NOT NULL DEFAULT '0',
              transferred_cost_basis_eur DECIMAL_TEXT NOT NULL DEFAULT '0',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS assets(
              symbol TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              kraken_pair TEXT NOT NULL,
              manual_price DECIMAL_TEXT NOT NULL DEFAULT '0',
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {row["name"] for row in con.execute("PRAGMA table_info(transactions)")}
        if "asset" not in columns:
            con.execute("ALTER TABLE transactions ADD COLUMN asset TEXT NOT NULL DEFAULT 'BTC'")
        if "asset_amount" not in columns and "btc_amount" in columns:
            con.execute("ALTER TABLE transactions RENAME COLUMN btc_amount TO asset_amount")

        _migrate_decimal_storage(con)

        con.execute("UPDATE transactions SET asset='EUR' WHERE type LIKE 'EUR %'")
        con.execute("UPDATE transactions SET asset='BTC', type=substr(type,5) WHERE type LIKE 'BTC %'")

        if not con.execute("SELECT 1 FROM assets LIMIT 1").fetchone():
            con.executemany(
                """INSERT INTO assets(symbol,name,kraken_pair,manual_price,sort_order)
                   VALUES (?,?,?,?,?)""",
                DEFAULT_ASSETS,
            )

        defaults = {"opening_cash": "0.01"}
        legacy = {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM settings")}
        for item in con.execute("SELECT symbol,manual_price FROM assets"):
            symbol = item["symbol"]
            manual = legacy.get("manual_price", item["manual_price"]) if symbol == "BTC" else item["manual_price"]
            price = legacy.get("price", manual) if symbol == "BTC" else manual
            source = legacy.get("price_source", "Handmatige terugvalprijs") if symbol == "BTC" else "Handmatige terugvalprijs"
            defaults[f"manual_price_{symbol}"] = str(manual)
            defaults[f"price_{symbol}"] = str(price)
            defaults[f"price_source_{symbol}"] = source
        for key, value in defaults.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP)",
                (key, value),
            )
        for symbol, in con.execute("SELECT symbol FROM assets"):
            manual = con.execute(
                "SELECT value FROM settings WHERE key=?", (f"manual_price_{symbol}",)
            ).fetchone()
            if manual:
                con.execute(
                    "UPDATE assets SET manual_price=? WHERE symbol=?",
                    (manual["value"], symbol),
                )

        if not con.execute("SELECT 1 FROM transactions LIMIT 1").fetchone():
            con.executemany(
                """INSERT INTO transactions(
                    tx_date,asset,type,description,asset_amount,eur_gross,fee_eur,transferred_cost_basis_eur
                ) VALUES (?,?,?,?,?,?,?,?)""",
                [tuple(format(Decimal(str(v)), "f") if i >= 4 else v for i, v in enumerate(row)) for row in SEED],
            )


def get_transactions():
    with closing(connect()) as con:
        return con.execute("SELECT * FROM transactions ORDER BY tx_date,id").fetchall()


def get_transaction(transaction_id):
    with closing(connect()) as con:
        return con.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()


def create_transaction(values):
    with closing(connect()) as con, con:
        cursor = con.execute(
            """INSERT INTO transactions(
                tx_date,asset,type,description,asset_amount,eur_gross,fee_eur,transferred_cost_basis_eur
            ) VALUES (:tx_date,:asset,:type,:description,:asset_amount,:eur_gross,:fee_eur,:transferred_cost_basis_eur)""",
            _decimal_values(values),
        )
        return cursor.lastrowid


def update_transaction(transaction_id, values):
    with closing(connect()) as con, con:
        cursor = con.execute(
            """UPDATE transactions SET
                tx_date=:tx_date,asset=:asset,type=:type,description=:description,
                asset_amount=:asset_amount,eur_gross=:eur_gross,fee_eur=:fee_eur,
                transferred_cost_basis_eur=:transferred_cost_basis_eur
            WHERE id=:id""",
            {**_decimal_values(values), "id": transaction_id},
        )
        return cursor.rowcount == 1


def delete_transaction(transaction_id):
    with closing(connect()) as con, con:
        return con.execute("DELETE FROM transactions WHERE id=?", (transaction_id,)).rowcount == 1


def get_settings():
    with closing(connect()) as con:
        return {row["key"]: row["value"] for row in con.execute("SELECT * FROM settings")}


def set_setting(key, value):
    with closing(connect()) as con, con:
        con.execute(
            """INSERT INTO settings(key,value) VALUES (?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
            (key, str(value)),
        )


def get_assets():
    with closing(connect()) as con:
        return con.execute("SELECT * FROM assets ORDER BY sort_order,symbol").fetchall()


def get_asset(symbol):
    with closing(connect()) as con:
        return con.execute("SELECT * FROM assets WHERE symbol=?", (symbol,)).fetchone()


def create_asset(values):
    with closing(connect()) as con, con:
        con.execute(
            """INSERT INTO assets(symbol,name,kraken_pair,manual_price,sort_order)
               VALUES (:symbol,:name,:kraken_pair,:manual_price,
                 COALESCE((SELECT MAX(sort_order) + 10 FROM assets),10))""",
            _decimal_values(values),
        )
        for key, value in (
            (f"manual_price_{values['symbol']}", values["manual_price"]),
            (f"price_{values['symbol']}", values["manual_price"]),
            (f"price_source_{values['symbol']}", "Handmatige terugvalprijs"),
        ):
            con.execute(
                "INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP)",
                (key, str(value)),
            )


def update_asset(symbol, values):
    with closing(connect()) as con, con:
        cursor = con.execute(
            """UPDATE assets SET name=:name,kraken_pair=:kraken_pair,
               manual_price=:manual_price WHERE symbol=:symbol""",
            {**_decimal_values(values), "symbol": symbol},
        )
        con.execute(
            """INSERT INTO settings(key,value) VALUES (?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
            (f"manual_price_{symbol}", str(values["manual_price"])),
        )
        source = con.execute(
            "SELECT value FROM settings WHERE key=?", (f"price_source_{symbol}",)
        ).fetchone()
        if not source or source["value"] == "Handmatige terugvalprijs":
            con.execute(
                """INSERT INTO settings(key,value) VALUES (?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                (f"price_{symbol}", str(values["manual_price"])),
            )
        return cursor.rowcount == 1


def asset_transaction_count(symbol):
    with closing(connect()) as con:
        return con.execute(
            "SELECT COUNT(*) FROM transactions WHERE asset=?", (symbol,)
        ).fetchone()[0]


def delete_asset(symbol):
    with closing(connect()) as con, con:
        if con.execute("SELECT 1 FROM transactions WHERE asset=? LIMIT 1", (symbol,)).fetchone():
            return False
        deleted = con.execute("DELETE FROM assets WHERE symbol=?", (symbol,)).rowcount == 1
        if deleted:
            con.execute(
                "DELETE FROM settings WHERE key IN (?,?,?,?)",
                (
                    f"manual_price_{symbol}",
                    f"price_{symbol}",
                    f"price_source_{symbol}",
                    f"price_updated_{symbol}",
                ),
            )
        return deleted
