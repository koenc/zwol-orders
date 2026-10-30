import unittest
import json
import datetime

import app.database as db_mod
db_mod._USE_SQLITE = True

from app.config import Config
Config.DB_HOST = None
Config.AUTH_BYPASS_FOR_DEV = True

from app.main import app, format_dutch_date, get_week_label
from app.database import get_db, init_db
from app.services.silvasoft_service import silvasoft_client


class TestZwolOrdersApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key"
        init_db()

    def setUp(self):
        self.client = app.test_client()

        # Vul wat proefdata in de database
        prefix = Config.DB_TABLE_PREFIX
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db() as db:
            # Klant
            db.execute(f"DELETE FROM {prefix}customers WHERE customer_number = 'TEST_1'")
            db.execute(f"""
                INSERT INTO {prefix}customers (
                    customer_number, name, contact_person, email, phone, street, unit, postal_code, city, is_customer, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, ("TEST_1", "Café Het Bruine Paard", "Jan de Vries", "jan@bruinepaard.nl", "0612345678", "Markt", "10", "2671AA", "Naaldwijk", 1, now_str))

            # Producten (met 'Tonen in ZWOL order app' = 1)
            db.execute(f"DELETE FROM {prefix}products WHERE article_number IN ('TEST_ZS', 'TEST_BM')")
            db.execute(f"""
                INSERT INTO {prefix}products (
                    article_number, name, short_name, show_in_order_app, category, price, vat_percentage, unit, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, ("TEST_ZS", "Zuipschuit 33cl 24 stuks", "ZS", 1, "Bier in fles", 62.48, 21.0, "Doos", now_str))

            db.execute(f"""
                INSERT INTO {prefix}products (
                    article_number, name, short_name, show_in_order_app, category, price, vat_percentage, unit, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, ("TEST_BM", "Barre Mannen 33cl 24 stuks", "BM", 1, "Bier in fles", 64.00, 21.0, "Doos", now_str))

            # Bestaande order
            db.execute(f"DELETE FROM {prefix}orders WHERE order_number = 'TEST_ORDER_999'")
            db.execute(f"""
                INSERT INTO {prefix}orders (
                    order_number, customer_number, customer_name, contact_person, phone,
                    address_street, address_unit, address_postal_code, address_city,
                    order_date, delivery_date, delivery_week, delivery_year,
                    status, reference, products_summary, order_lines_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, ("TEST_ORDER_999", "TEST_1", "Café Het Bruine Paard", "Jan de Vries", "0612345678",
                  "Markt", "10", "2671AA", "Naaldwijk", "30-10-2026", "31-10-2026", 44, 2026,
                  "Bevestigd", "Levering 31-10-2026", "2xZS, 1xBM",
                  json.dumps([{"Description": "Zuipschuit 33cl 24 stuks", "Quantity": 2}, {"Description": "Barre Mannen 33cl 24 stuks", "Quantity": 1}]),
                  now_str, now_str))

            # Mock sync log om netwerk calls tijdens tests te voorkomen
            db.execute(f"DELETE FROM {prefix}sync_log")
            db.execute(f"INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at) VALUES ('orders', 'success', 1, 'mock', '{now_str}')")
            db.execute(f"INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at) VALUES ('products', 'success', 2, 'mock', '{now_str}')")
            db.execute(f"INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at) VALUES ('customers', 'success', 1, 'mock', '{now_str}')")

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "healthy")

    def test_board_page(self):
        resp = self.client.get("/board")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ZWOL ORDERS".encode(), resp.data)
        self.assertIn("Leveroverzicht".encode(), resp.data)

    def test_create_order_page(self):
        resp = self.client.get("/create")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Nieuwe Bierorder Invoeren".encode(), resp.data)

    def test_api_products(self):
        resp = self.client.get("/api/products")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        names = [p["name"] for p in data["products"]]
        self.assertIn("Zuipschuit 33cl 24 stuks", names)

    def test_api_customers_search(self):
        resp = self.client.get("/api/customers?q=Bruine")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertTrue(any("Bruine Paard" in c["name"] for c in data["customers"]))

    def test_api_orders_kanban(self):
        resp = self.client.get("/api/orders")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(len(data.get("weeks", [])), 1)

    def test_api_order_detail(self):
        resp = self.client.get("/api/orders/TEST_ORDER_999")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["order"]["customer_name"], "Café Het Bruine Paard")
        self.assertEqual(len(data["order"]["order_lines"]), 2)

    def test_date_formatting(self):
        formatted = format_dutch_date("31-10-2026")
        self.assertTrue(formatted.endswith("okt"))
        week_label = get_week_label(2026, 44)
        self.assertTrue(len(week_label) > 0)
        # Test 2-part and 3-part conversion
        self.assertEqual(silvasoft_client._format_nl_date("2026-11-04"), "04-11-2026")
        self.assertTrue(silvasoft_client._format_nl_date("04-11").startswith("04-11-"))
        week, year = silvasoft_client._parse_week_and_year("04-11-2026")
        self.assertEqual(week, 45)
        self.assertEqual(year, 2026)

    def test_api_create_order_validation(self):
        # Missing customer name
        resp = self.client.post("/api/orders", json={"items": [{"article_number": "123", "quantity": 1}]})
        self.assertEqual(resp.status_code, 400)
        # Missing items
        resp = self.client.post("/api/orders", json={"customer_name": "Test Klant", "items": []})
        self.assertEqual(resp.status_code, 400)

    def test_scheduler_lifecycle(self):
        from app.scheduler import start_background_scheduler, stop_background_scheduler
        start_background_scheduler()
        stop_background_scheduler()

    def test_pwa_installability(self):
        # Manifest
        resp = self.client.get("/manifest.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("display"), "standalone")
        self.assertGreaterEqual(len(data.get("icons", [])), 2)

        # Service Worker
        resp_sw = self.client.get("/sw.js")
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn("Service-Worker-Allowed", resp_sw.headers)

        # Icons
        resp_icon = self.client.get("/static/img/icon-192.png")
        self.assertEqual(resp_icon.status_code, 200)


if __name__ == "__main__":
    unittest.main()
