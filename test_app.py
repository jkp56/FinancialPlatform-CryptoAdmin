import io
import html
import json
import re
import sqlite3
import unittest
import urllib.parse
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from wsgiref.util import setup_testing_defaults

import db
from app import application, crypto_amount, pnl_chart, run_server, signed_money
from calculations import build_ledger


def tx(
    transaction_id,
    tx_date,
    asset,
    kind,
    amount=0,
    eur=0,
    fee=0,
    cost=0,
    description="",
):
    return {
        "id": transaction_id,
        "tx_date": tx_date,
        "asset": asset,
        "type": kind,
        "description": description,
        "asset_amount": amount,
        "eur_gross": eur,
        "fee_eur": fee,
        "transferred_cost_basis_eur": cost,
    }


class CryptoAdminTest(unittest.TestCase):
    def test_existing_numeric_database_migrates_once_with_backup(self):
        with TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "test.sqlite3"):
            with closing(sqlite3.connect(db.DB_PATH)) as con, con:
                con.execute("""CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY, tx_date TEXT, asset TEXT, type TEXT,
                    description TEXT, asset_amount NUMERIC, eur_gross NUMERIC,
                    fee_eur NUMERIC, transferred_cost_basis_eur NUMERIC,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
                con.execute("INSERT INTO transactions VALUES (42,'2026-09-10','BTC','Reward','Reward',0.0000003166,0,0,0,'original')")
            db.init_db()
            self.assertEqual(db.get_transaction(42)["asset_amount"], Decimal("0.0000003166"))
            self.assertEqual(db.get_transaction(42)["created_at"], "original")
            backup = db.DB_PATH.with_name("test.pre_decimal.sqlite3")
            self.assertTrue(backup.exists())
            before = backup.read_bytes()
            db.init_db()
            self.assertEqual(backup.read_bytes(), before)
            values = dict(db.get_transaction(42))
            for field in ("asset_amount", "eur_gross", "fee_eur", "transferred_cost_basis_eur"):
                values[field] = "123.456789012345678901234567890123"
            db.update_transaction(42, values)
            for field in ("asset_amount", "eur_gross", "fee_eur", "transferred_cost_basis_eur"):
                self.assertEqual(db.get_transaction(42)[field], Decimal(values[field]))

    def test_decimal_storage_and_edit_form_round_trip(self):
        with TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "test.sqlite3"):
            db.init_db()
            values = tx(0, "2026-09-12", "BTC", "Storting",
                        "0.0000003166000000000123456789", cost="1234.567890123456789012345678")
            transaction_id = db.create_transaction(values)
            saved = db.get_transaction(transaction_id)
            self.assertEqual(saved["asset_amount"], Decimal(values["asset_amount"]))
            self.assertEqual(saved["transferred_cost_basis_eur"], Decimal(values["transferred_cost_basis_eur"]))
            status, body = self.get("/transactions")
            payloads = [json.loads(html.unescape(value)) for value in re.findall(r'data-transaction="([^"]+)"', body)]
            edit = next(value for value in payloads if value["id"] == transaction_id)
            self.assertEqual(edit["asset_amount"], values["asset_amount"])
            self.assertEqual(edit["transferred_cost_basis_eur"], values["transferred_cost_basis_eur"])
            status, _ = self.post("/transactions", edit)
            self.assertEqual(status, "303 See Other")
            self.assertEqual(db.get_transaction(transaction_id)["asset_amount"], saved["asset_amount"])
            db.init_db()
            self.assertEqual(db.get_transaction(transaction_id)["transferred_cost_basis_eur"], saved["transferred_cost_basis_eur"])

    def test_plain_decimal_display_for_all_numeric_fields(self):
        from app import decimal_text, money, transactions, settings_page
        self.assertEqual(decimal_text(Decimal("3.166E-7")), "0.0000003166")
        self.assertEqual(crypto_amount(Decimal("1.23456789E-16")), "0.000000000000000123456789")
        self.assertEqual(crypto_amount(100), "100.00000000")
        self.assertEqual(money(Decimal("123.4567")), "€ 123,4567")
        self.assertEqual(money(Decimal("1E-16")), "€ 0,0000000000000001")
        body = transactions([], [], "Controleer invoer", {"asset_amount": "3.166E-7", "fee_eur": "1E-8"})
        self.assertIn('value="0.0000003166"', body)
        self.assertIn('value="0.00000001"', body)
        with TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "test.sqlite3"):
            db.init_db()
            db.create_asset({"symbol": "TEST", "name": "Test", "kraken_pair": "TESTEUR", "manual_price": "0.000000000123456789123456789"})
            self.assertEqual(db.get_asset("TEST")["manual_price"], Decimal("0.000000000123456789123456789"))
            body = settings_page({**db.get_settings(), "opening_cash": "1E-8"}, db.get_assets())
            self.assertIn('value="0.00000001"', body)
            self.assertIn('value="0.000000000123456789123456789"', body)

    def test_dust_sweep_multiple_assets_and_fees(self):
        rows, metrics = build_ledger([
            tx(1, "2026-09-10", "USD", "Storting", "0.0085", cost="0.008"),
            tx(2, "2026-09-10", "ETH", "Storting", "0.0000013466", cost="0.004"),
            tx(3, "2026-09-11", "USD", "Dust sweeping", "0.0085", "0.007", "0.0002"),
            tx(4, "2026-09-11", "ETH", "Dust sweeping", "0.0000013466", "0.0028", "0.0001"),
        ], 0, {"USD": 1, "ETH": 3000})
        self.assertEqual(metrics["cash"], Decimal("0.0098"))
        self.assertEqual(metrics["external"], Decimal("0.012"))
        self.assertEqual(metrics["realized"], Decimal("-0.0022"))
        for asset in metrics["assets"].values():
            self.assertEqual(asset["balance"], 0)
            self.assertEqual(asset["cost_basis"], 0)
        self.assertTrue(all(not row["control"] for row in rows))

    def test_dust_sweep_form_precision_and_validation(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            values = tx(0, "2026-09-11", "BTC", "Dust sweeping", "0.0000013466", "0.0098", "0.0003")
            values.pop("id")
            status, _ = self.post("/transactions", values)
            self.assertEqual(status, "303 See Other")
            saved = dict(db.get_transactions()[-1])
            self.assertEqual(Decimal(str(saved["eur_gross"])), Decimal("0.0098"))
            self.assertEqual(Decimal(str(saved["fee_eur"])), Decimal("0.0003"))
            status, body = self.get("/transactions")
            self.assertIn("€ 0,0098", body)
            self.assertIn("€ 0,0003", body)
            self.assertIn('step="any" min="0" name="eur_gross"', body)
            status, _ = self.post("/transactions", {**values, "eur_gross": "0"})
            self.assertEqual(status, "303 See Other")
            status, _ = self.post("/transactions", {**values, "asset_amount": "100"})
            self.assertEqual(status, "422 Unprocessable Entity")
            status, _ = self.post("/transactions", {**values, "eur_gross": "-0.01"})
            self.assertEqual(status, "422 Unprocessable Entity")

    def post(self, path, data):
        payload = urllib.parse.urlencode(data).encode()
        environ = {}
        setup_testing_defaults(environ)
        environ.update(
            {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": path,
                "CONTENT_LENGTH": str(len(payload)),
                "wsgi.input": io.BytesIO(payload),
            }
        )
        response = {}
        body = b"".join(
            application(
                environ,
                lambda status, headers: response.update(status=status, headers=headers),
            )
        )
        return response["status"], body.decode()

    def get(self, path):
        environ = {}
        setup_testing_defaults(environ)
        environ["PATH_INFO"] = path
        response = {}
        body = b"".join(
            application(
                environ,
                lambda status, headers: response.update(status=status, headers=headers),
            )
        )
        return response["status"], body.decode()

    def test_health_endpoint_does_not_require_database(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, "200 OK")
        self.assertEqual(body, "ok")

    def test_signed_money_describes_cash_direction(self):
        self.assertEqual(signed_money(Decimal("150")), "+ € 150,00")
        self.assertEqual(signed_money(Decimal("-172.77")), "− € 172,77")
        self.assertEqual(signed_money(Decimal("0")), "–")

    def test_transaction_page_has_coin_and_type_filters(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            status, body = self.get("/transactions")
            self.assertEqual(status, "200 OK")
            self.assertIn('id="transaction-filter-asset"', body)
            self.assertIn('id="transaction-filter-type"', body)
            self.assertIn('data-asset="BTC" data-type="Inkoop"', body)
            self.assertIn("EUR-kasmutatie", body)
            self.assertIn("− € 50,00", body)
            self.assertIn("+ € 50,00", body)

            newest = body.index('data-asset="BTC" data-type="Verkoop"')
            oldest = body.index('data-asset="BTC" data-type="Storting"')
            self.assertLess(newest, oldest)

    def test_transaction_crud_for_eth(self):
        values = {
            "tx_date": "2026-07-20",
            "asset": "ETH",
            "type": "Inkoop",
            "description": "ETH aankoop",
            "asset_amount": "0.025",
            "eur_gross": "75",
            "fee_eur": "0.50",
            "transferred_cost_basis_eur": "0",
        }
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            transaction_id = db.create_transaction(values)
            self.assertEqual(db.get_transaction(transaction_id)["asset"], "ETH")
            corrected = {**values, "description": "Gecorrigeerd", "fee_eur": "0.40"}
            self.assertTrue(db.update_transaction(transaction_id, corrected))
            self.assertEqual(db.get_transaction(transaction_id)["description"], "Gecorrigeerd")
            self.assertTrue(db.delete_transaction(transaction_id))
            self.assertIsNone(db.get_transaction(transaction_id))

    def test_asset_can_be_added_used_and_not_deleted_while_referenced(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            status, _ = self.post(
                "/assets/create",
                {
                    "symbol": "sol",
                    "name": "Solana",
                    "kraken_pair": "SOL/EUR",
                    "manual_price": "125.50",
                },
            )
            self.assertEqual(status, "303 See Other")
            self.assertEqual(db.get_asset("SOL")["kraken_pair"], "SOLEUR")
            self.assertEqual(db.get_settings()["price_SOL"], "125.50")

            status, _ = self.post(
                "/transactions",
                {
                    "tx_date": "2026-07-20",
                    "asset": "SOL",
                    "type": "Reward",
                    "description": "SOL reward",
                    "asset_amount": "0.01",
                },
            )
            self.assertEqual(status, "303 See Other")
            self.assertEqual(db.get_transactions()[-1]["asset"], "SOL")

            status, body = self.post("/assets/delete", {"symbol": "SOL"})
            self.assertEqual(status, "422 Unprocessable Entity")
            self.assertIn("kan niet worden verwijderd", body)
            self.assertIsNotNone(db.get_asset("SOL"))

    def test_dynamic_asset_is_included_in_ledger_metrics(self):
        transactions = [tx(1, "2026-07-01", "SOL", "Storting", "2", cost="200")]
        _, metrics = build_ledger(transactions, Decimal("0"), {"SOL": "125"})
        self.assertEqual(metrics["assets"]["SOL"]["balance"], Decimal("2"))
        self.assertEqual(metrics["assets"]["SOL"]["market"], Decimal("250"))
        self.assertEqual(metrics["total_pnl"], Decimal("50"))

    def test_unreferenced_asset_can_be_deleted(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            db.create_asset(
                {
                    "symbol": "SOL",
                    "name": "Solana",
                    "kraken_pair": "SOLEUR",
                    "manual_price": "100",
                }
            )
            status, _ = self.post("/assets/delete", {"symbol": "SOL"})
            self.assertEqual(status, "303 See Other")
            self.assertIsNone(db.get_asset("SOL"))
            self.assertNotIn("price_SOL", db.get_settings())

    def test_deleted_default_asset_stays_deleted_after_restart(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            self.assertTrue(db.delete_asset("ETH"))
            db.init_db()
            self.assertIsNone(db.get_asset("ETH"))
            self.assertNotIn("price_ETH", db.get_settings())

    def test_legacy_database_is_backed_up_and_migrated_to_btc(self):
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "legacy.sqlite3"
            con = sqlite3.connect(database)
            con.executescript(
                """
                CREATE TABLE transactions(
                  id INTEGER PRIMARY KEY, tx_date TEXT, type TEXT, description TEXT,
                  btc_amount NUMERIC, eur_gross NUMERIC, fee_eur NUMERIC,
                  transferred_cost_basis_eur NUMERIC, created_at TEXT
                );
                CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);
                INSERT INTO transactions VALUES
                  (1,'2026-07-01','BTC Inkoop','Oud',0.001,50,0.5,0,''),
                  (2,'2026-07-02','EUR Storting','EUR',0,25,0,0,'');
                INSERT INTO settings VALUES ('price','56000','');
                INSERT INTO settings VALUES ('manual_price','55000','');
                """
            )
            con.commit()
            con.close()
            with patch.object(db, "DB_PATH", database):
                db.init_db()
                rows = db.get_transactions()
                self.assertTrue(database.with_name("crypto_admin.pre_multi_asset.sqlite3").exists())
                self.assertEqual(rows[0]["asset"], "BTC")
                self.assertEqual(rows[0]["type"], "Inkoop")
                self.assertEqual(rows[0]["asset_amount"], Decimal("0.001"))
                self.assertEqual(rows[1]["asset"], "EUR")
                self.assertEqual(db.get_settings()["price_BTC"], "56000")

    @patch("app.db.init_db")
    def test_ctrl_c_stops_server_without_traceback(self, init_db):
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        factory = Mock(return_value=server)
        run_server(factory)
        init_db.assert_called_once_with()
        server.server_close.assert_called_once_with()

    def test_small_reward_keeps_precision_for_both_assets(self):
        transactions = [
            tx(1, "2026-07-16", "BTC", "Reward", "0.0000002215"),
            tx(2, "2026-07-16", "ETH", "Reward", "0.000000000123"),
        ]
        _, metrics = build_ledger(
            transactions, Decimal("0"), {"BTC": "57121.85", "ETH": "3000"}
        )
        self.assertEqual(metrics["assets"]["BTC"]["balance"], Decimal("0.0000002215"))
        self.assertEqual(metrics["assets"]["ETH"]["balance"], Decimal("0.000000000123"))
        self.assertEqual(crypto_amount(metrics["assets"]["BTC"]["balance"]), "0.0000002215")

    def test_purchase_total_includes_fee_per_asset(self):
        transactions = [
            tx(1, "2026-07-01", "EUR", "EUR Storting", eur="200"),
            tx(2, "2026-07-02", "BTC", "Inkoop", "0.001", "50", "0.50"),
            tx(3, "2026-07-03", "ETH", "Inkoop", "0.025", "75", "0.75"),
        ]
        rows, metrics = build_ledger(
            transactions, Decimal("0"), {"BTC": "56000", "ETH": "3100"}
        )
        self.assertEqual(rows[1]["reference_price"], Decimal("49.50") / Decimal("0.001"))
        self.assertEqual(rows[2]["reference_price"], Decimal("74.25") / Decimal("0.025"))
        self.assertEqual(metrics["cash"], Decimal("75"))
        self.assertEqual(metrics["assets"]["BTC"]["cost_basis"], Decimal("50"))
        self.assertEqual(metrics["assets"]["ETH"]["cost_basis"], Decimal("75"))

    def test_eth_sale_only_changes_eth_cost_basis_and_pnl(self):
        transactions = [
            tx(1, "2026-07-01", "BTC", "Storting", "0.001", cost="50"),
            tx(2, "2026-07-01", "ETH", "Storting", "1", cost="2500"),
            tx(3, "2026-07-02", "ETH", "Verkoop", "0.25", "800", "2"),
        ]
        rows, metrics = build_ledger(
            transactions, Decimal("0"), {"BTC": "56000", "ETH": "3200"}
        )
        sale = rows[2]
        self.assertEqual(sale["removed_cost_basis"], Decimal("625"))
        self.assertEqual(sale["pnl_tx"], Decimal("175"))
        self.assertEqual(metrics["assets"]["ETH"]["balance"], Decimal("0.75"))
        self.assertEqual(metrics["assets"]["BTC"]["balance"], Decimal("0.001"))
        self.assertEqual(metrics["realized"], Decimal("175"))

    def test_combined_metrics_equal_sum_of_coin_metrics(self):
        transactions = [
            tx(1, "2026-07-01", "BTC", "Storting", "0.001", cost="50"),
            tx(2, "2026-07-01", "ETH", "Storting", "0.5", cost="1200"),
        ]
        _, metrics = build_ledger(
            transactions, Decimal("10"), {"BTC": "60000", "ETH": "3000"}
        )
        btc_metrics = metrics["assets"]["BTC"]
        eth_metrics = metrics["assets"]["ETH"]
        self.assertEqual(metrics["market"], btc_metrics["market"] + eth_metrics["market"])
        self.assertEqual(
            metrics["total_pnl"], btc_metrics["total_pnl"] + eth_metrics["total_pnl"]
        )
        self.assertEqual(metrics["account_value"], metrics["market"] + Decimal("10"))

    def test_seed_reconciles_as_btc_only(self):
        transactions = [
            tx(index, row[0], row[1], row[2], row[4], row[5], row[6], row[7], row[3])
            for index, row in enumerate(db.SEED, 1)
        ]
        rows, metrics = build_ledger(
            transactions, Decimal("0.01"), {"BTC": "57121.85", "ETH": "3000"}
        )
        self.assertEqual(metrics["assets"]["BTC"]["balance"], Decimal("0.01275016"))
        self.assertEqual(metrics["assets"]["ETH"]["balance"], Decimal("0"))
        self.assertAlmostEqual(float(metrics["cash"]), 25.01, places=8)
        self.assertFalse([row for row in rows if row["control"]])

    def test_invalid_eth_sale_is_not_saved_and_error_is_shown(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            before = len(db.get_transactions())
            status, body = self.post(
                "/transactions",
                {
                    "tx_date": "2026-07-20",
                    "asset": "ETH",
                    "type": "Verkoop",
                    "description": "Te veel",
                    "asset_amount": "1",
                    "eur_gross": "10",
                    "fee_eur": "0",
                },
            )
            self.assertEqual(status, "422 Unprocessable Entity")
            self.assertIn("Onvoldoende ETH", body)
            self.assertIn('data-validation-error="true"', body)
            self.assertEqual(len(db.get_transactions()), before)

    def test_deletion_that_breaks_later_purchase_is_blocked(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            db, "DB_PATH", Path(temp_dir) / "test.sqlite3"
        ):
            db.init_db()
            status, body = self.post("/delete", {"id": "2"})
            self.assertEqual(status, "422 Unprocessable Entity")
            self.assertIn("onvoldoende eur", body.lower())
            self.assertIsNotNone(db.get_transaction(2))

    def test_chart_uses_dynamic_scale_and_stays_inside_viewbox(self):
        rows = [
            {
                "tx_date": f"2026-07-{index + 1:02d}",
                "asset": "BTC" if index % 2 == 0 else "ETH",
                "type": "Inkoop",
                "historical_total": Decimal(-40 + index * 7),
            }
            for index in range(20)
        ]
        chart = pnl_chart(rows)
        points = re.search(r'class="chart-line" points="([^"]+)"', chart).group(1)
        coordinates = [tuple(map(float, point.split(","))) for point in points.split()]
        self.assertEqual(len(coordinates), 20)
        self.assertAlmostEqual(coordinates[0][0], 8)
        self.assertAlmostEqual(coordinates[-1][0], 992)
        self.assertTrue(all(8 <= x <= 992 and 8 <= y <= 132 for x, y in coordinates))
        self.assertIn("Gezamenlijk PnL-verloop", chart)


if __name__ == "__main__":
    unittest.main()
