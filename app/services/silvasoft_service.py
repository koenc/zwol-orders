import datetime
import json
import logging
import time
import urllib3
import requests
from app.config import Config
from app.database import get_db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("zwol_orders")


class SilvasoftClient:
    def __init__(self):
        self.base_url = Config.SILVASOFT_BASE_URL
        self.username = Config.SILVASOFT_USERNAME
        self.api_key = Config.SILVASOFT_API_KEY

    def _headers(self):
        return {
            "ApiKey": self.api_key,
            "Username": self.username,
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, params=None, json_data=None):
        if not self.username or not self.api_key:
            raise ValueError("Silvasoft API-inloggegevens ontbreken in de configuratie.")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Maximaal 3 pogingen met automatische rate-limit backoff
        for attempt in range(3):
            # Altijd 550ms pauze om onder de 2 requests/sec te blijven
            time.sleep(0.55)
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=self._headers(),
                    params=params,
                    json=json_data,
                    timeout=15,
                    verify=False
                )
                if (resp.status_code == 401 or resp.status_code == 429) and "Ratelimit exceeded" in resp.text:
                    if attempt == 2:
                        raise RuntimeError("Silvasoft API rate limit overschreden (maximaal 50 verzoeken per minuut). Wacht a.u.b. een minuut en probeer het opnieuw.")
                    logger.warning(f"Silvasoft rate limit bereikt (poging {attempt+1}/3). 3.0 seconden wachten...")
                    time.sleep(3.0)
                    continue

                if resp.status_code not in (200, 201):
                    logger.error(f"Silvasoft API fout ({method} {endpoint} HTTP {resp.status_code}): {resp.text}")
                    err_msg = resp.text
                    try:
                        err_json = resp.json()
                        if isinstance(err_json, dict):
                            msg = err_json.get("errorMessage") or err_json.get("message")
                            details = err_json.get("Details") or err_json.get("details")
                            code = err_json.get("errorCode") or err_json.get("code")
                            parts = []
                            if msg:
                                parts.append(str(msg).strip())
                            if details and str(details).strip() not in (str(msg).strip(), ""):
                                parts.append(f"Details: {str(details).strip()}")
                            if code:
                                parts.append(f"Code: {code}")
                            if parts:
                                err_msg = " — ".join(parts)
                    except Exception:
                        pass
                    raise RuntimeError(f"Silvasoft API fout ({resp.status_code}): {err_msg}")

                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    logger.error(f"Fout bij communicatie met Silvasoft ({method} {endpoint}): {e}")
                    raise RuntimeError(f"Verbindingsfout met Silvasoft: {e}")
                time.sleep(1.5)

        raise RuntimeError(f"Silvasoft API aanroep naar {endpoint} kon niet worden voltooid na 3 pogingen.")

    # --------------------------------------------------------------------------
    # 1. Producten Synchroniseren
    # --------------------------------------------------------------------------
    def sync_products(self) -> int:
        """Haalt alle producten op uit Silvasoft en filtert op 'Tonen in ZWOL order app'."""
        logger.info("Start synchronisatie producten vanuit Silvasoft...")
        offset = 0
        limit = 100
        all_products = []

        while True:
            data = self._request("GET", "listproducts/", params={"offset": offset, "limit": limit})
            if not isinstance(data, list) or len(data) == 0:
                break
            all_products.extend(data)
            if len(data) < limit:
                break
            offset += limit

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = Config.DB_TABLE_PREFIX
        synced_count = 0

        with get_db() as db:
            for p in all_products:
                cfs = p.get("ProductResponse_CustomField") or []
                show_in_order_app = False
                short_name = ""

                for cf in cfs:
                    label = (cf.get("Label") or "").strip().lower()
                    if label == "tonen in zwol order app":
                        show_in_order_app = bool(cf.get("BooleanValue") is True or str(cf.get("StringValue")).strip() in ("1", "true"))
                    elif label == "korte naam":
                        short_name = (cf.get("StringValue") or "").strip().upper()

                article_number = str(p.get("ArticleNumber") or "").strip()
                if not article_number:
                    continue

                name = (p.get("Name") or "").strip()
                category = (p.get("Category") or "").strip()
                price = float(p.get("Price") or 0.0)
                vat_percentage = float(p.get("VATPercentage") or 21.0)
                unit = (p.get("Unit") or "Stuks").strip()

                # Upsert product
                existing = db.fetchone(f"SELECT article_number FROM {prefix}products WHERE article_number = %s", (article_number,))
                if existing:
                    db.execute(f"""
                        UPDATE {prefix}products
                        SET name = %s, short_name = %s, show_in_order_app = %s, category = %s,
                            price = %s, vat_percentage = %s, unit = %s, updated_at = %s
                        WHERE article_number = %s
                    """, (name, short_name, 1 if show_in_order_app else 0, category, price, vat_percentage, unit, now_str, article_number))
                else:
                    db.execute(f"""
                        INSERT INTO {prefix}products (
                            article_number, name, short_name, show_in_order_app, category, price, vat_percentage, unit, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (article_number, name, short_name, 1 if show_in_order_app else 0, category, price, vat_percentage, unit, now_str))

                if show_in_order_app:
                    synced_count += 1

            # Log sync
            db.execute(f"""
                INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, ("products", "success", synced_count, f"{len(all_products)} producten opgehaald, {synced_count} actief in app", now_str))

        logger.info(f"Product synchronisatie voltooid: {synced_count} actieve ZWOL bieren/producten opgeslagen.")
        return synced_count

    # --------------------------------------------------------------------------
    # 2. Relaties (Klanten) Synchroniseren
    # --------------------------------------------------------------------------
    def sync_customers(self) -> int:
        """Haalt alle klanten/relaties op uit Silvasoft voor autocomplete."""
        logger.info("Start synchronisatie klanten vanuit Silvasoft...")
        offset = 0
        limit = 100
        all_relations = []

        while True:
            params = {
                "relationtype": "Customer",
                "offset": offset,
                "limit": limit
            }
            data = self._request("GET", "listrelations/", params=params)
            if not isinstance(data, list) or len(data) == 0:
                break
            all_relations.extend(data)
            if len(data) < limit or len(all_relations) >= 500:
                break
            offset += limit

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = Config.DB_TABLE_PREFIX
        synced_count = 0

        with get_db() as db:
            for r in all_relations:
                customer_number = str(r.get("CustomerNumber") or 0)
                is_customer = bool(r.get("IsCustomer"))
                # Ook relaties met customer_number > 0 als klant beschouwen
                if not is_customer and (customer_number == "0" or not customer_number):
                    continue

                name = (r.get("Name") or "").strip()
                if not name:
                    continue

                email = (r.get("Email") or "").strip()
                phone = (r.get("Phone") or "").strip()
                street = (r.get("Address_Street") or "").strip()
                unit = (r.get("Address_Unit") or "").strip()
                postal_code = (r.get("Address_PostalCode") or "").strip()
                city = (r.get("Address_City") or "").strip()
                group_name = (r.get("GroupName") or "").strip()

                # Contactpersoon uit Relation_Contact halen indien aanwezig
                contact_person = ""
                contacts = r.get("Relation_Contact") or []
                if contacts and isinstance(contacts, list):
                    first_contact = contacts[0]
                    c_first = (first_contact.get("FirstName") or "").strip()
                    c_last = (first_contact.get("LastName") or first_contact.get("FamilyName") or "").strip()
                    contact_person = f"{c_first} {c_last}".strip()
                    if not phone and first_contact.get("Phone"):
                        phone = str(first_contact.get("Phone")).strip()
                    if not email and first_contact.get("Email"):
                        email = str(first_contact.get("Email")).strip()

                existing = db.fetchone(f"SELECT customer_number FROM {prefix}customers WHERE customer_number = %s", (customer_number,))
                if existing:
                    db.execute(f"""
                        UPDATE {prefix}customers
                        SET name = %s, contact_person = %s, email = %s, phone = %s,
                            street = %s, unit = %s, postal_code = %s, city = %s, group_name = %s,
                            is_customer = 1, updated_at = %s
                        WHERE customer_number = %s
                    """, (name, contact_person, email, phone, street, unit, postal_code, city, group_name, now_str, customer_number))
                else:
                    db.execute(f"""
                        INSERT INTO {prefix}customers (
                            customer_number, name, contact_person, email, phone,
                            street, unit, postal_code, city, group_name, is_customer, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (customer_number, name, contact_person, email, phone, street, unit, postal_code, city, group_name, 1, now_str))

                synced_count += 1

            # Log sync
            db.execute(f"""
                INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, ("customers", "success", synced_count, f"{synced_count} klanten gesynchroniseerd", now_str))

        logger.info(f"Klanten synchronisatie voltooid: {synced_count} klanten opgeslagen.")
        return synced_count

    # --------------------------------------------------------------------------
    # 3. Orders Synchroniseren
    # --------------------------------------------------------------------------
    def sync_orders(self) -> int:
        """Haalt alle orders op uit Silvasoft en berekent weeknummers en productcodes."""
        logger.info("Start synchronisatie orders vanuit Silvasoft...")
        prefix = Config.DB_TABLE_PREFIX

        # Map van korte namen uit producten tabel laden voor snelle afkortingen
        product_short_map = {}
        with get_db() as db:
            prods = db.fetchall(f"SELECT article_number, name, short_name FROM {prefix}products")
            for p in prods:
                if p.get("article_number"):
                    product_short_map[str(p["article_number"]).strip()] = p.get("short_name") or ""
                if p.get("name"):
                    product_short_map[p["name"].strip().lower()] = p.get("short_name") or ""

        offset = 0
        limit = 50
        all_orders = []

        # Filter DIRECT op 'OrderStatus=Bevestigd' om te voorkomen dat duizenden oude orders worden opgehaald!
        while True:
            params = {
                "OrderStatus": "Bevestigd",
                "offset": offset,
                "limit": limit
            }
            data = self._request("GET", "listorders/", params=params)
            if not isinstance(data, list) or len(data) == 0:
                break
            all_orders.extend(data)
            if len(data) < limit:
                break
            offset += limit

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        synced_count = 0

        with get_db() as db:
            # Batch map voor directe contactpersoon & telefoon lookup zonder losse SQL queries
            cust_rows = db.fetchall(f"SELECT customer_number, contact_person, phone FROM {prefix}customers")
            cust_map = {str(c["customer_number"]): (c.get("contact_person") or "", c.get("phone") or "") for c in cust_rows if c.get("customer_number")}

            for o in all_orders:
                order_number = str(o.get("OrderNumber") or 0)
                if order_number == "0":
                    continue

                status = (o.get("OrderStatus") or "Bevestigd").strip()
                customer_number = str(o.get("CustomerNumber") or "")
                customer_name = (o.get("CustomerName") or "").strip()
                order_date = (o.get("OrderDate") or "").strip()
                reference = (o.get("OrderReference") or "").strip()
                order_lines = o.get("Order_Orderline") or []

                # Bepaal leverdatum
                delivery_date = ""
                for line in order_lines:
                    if line.get("DeliveryDate"):
                        delivery_date = line.get("DeliveryDate").strip()
                        break
                if not delivery_date:
                    delivery_date = order_date

                # Weeknummer en jaar berekenen
                d_week, d_year = self._parse_week_and_year(delivery_date)

                # Producten samenvatting (bijv. "1x ZS, 3x BM, 2x OG")
                summary_parts = []
                for line in order_lines:
                    qty = int(float(line.get("Quantity") or 0))
                    if qty <= 0:
                        continue
                    p_num = str(line.get("ProductNumber") or "").strip()
                    desc = (line.get("Description") or "").strip()
                    short = product_short_map.get(p_num) or product_short_map.get(desc.lower())
                    if not short and desc:
                        # Fallback afkorting: eerste letters
                        words = desc.split()
                        short = "".join(w[0].upper() for w in words[:2])
                    label = short if short else desc
                    summary_parts.append(f"{qty}x {label}")

                products_summary = ", ".join(summary_parts) if summary_parts else "Geen artikelen"

                # Verzendadres en contact opzoeken
                addresses = o.get("Order_Address") or []
                street = unit = postal_code = city = ""
                for addr in addresses:
                    if addr.get("Address_Type") == "ShippingAddress":
                        street = (addr.get("Address_Street") or "").strip()
                        unit = (addr.get("Address_Unit") or "").strip()
                        postal_code = (addr.get("Address_PostalCode") or "").strip()
                        city = (addr.get("Address_City") or "").strip()
                        break
                if not street and addresses:
                    first = addresses[0]
                    street = (first.get("Address_Street") or "").strip()
                    unit = (first.get("Address_Unit") or "").strip()
                    postal_code = (first.get("Address_PostalCode") or "").strip()
                    city = (first.get("Address_City") or "").strip()

                # Telefoon en contactpersoon opzoeken in customers cache
                contact_info = cust_map.get(customer_number, ("", ""))
                contact_person = contact_info[0]
                phone = contact_info[1]

                order_lines_json = json.dumps(order_lines)

                existing = db.fetchone(f"SELECT order_number FROM {prefix}orders WHERE order_number = %s", (order_number,))
                if existing:
                    db.execute(f"""
                        UPDATE {prefix}orders
                        SET customer_number = %s, customer_name = %s, contact_person = %s, phone = %s,
                            address_street = %s, address_unit = %s, address_postal_code = %s, address_city = %s,
                            order_date = %s, delivery_date = %s, delivery_week = %s, delivery_year = %s,
                            status = %s, reference = %s, products_summary = %s, order_lines_json = %s, updated_at = %s
                        WHERE order_number = %s
                    """, (customer_number, customer_name, contact_person, phone, street, unit, postal_code, city,
                          order_date, delivery_date, d_week, d_year, status, reference, products_summary, order_lines_json, now_str, order_number))
                else:
                    db.execute(f"""
                        INSERT INTO {prefix}orders (
                            order_number, customer_number, customer_name, contact_person, phone,
                            address_street, address_unit, address_postal_code, address_city,
                            order_date, delivery_date, delivery_week, delivery_year,
                            status, reference, products_summary, order_lines_json, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (order_number, customer_number, customer_name, contact_person, phone,
                          street, unit, postal_code, city, order_date, delivery_date, d_week, d_year,
                          status, reference, products_summary, order_lines_json, now_str, now_str))

                synced_count += 1

            # Log sync
            db.execute(f"""
                INSERT INTO {prefix}sync_log (sync_type, status, records_count, message, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, ("orders", "success", synced_count, f"{synced_count} orders gesynchroniseerd", now_str))

        logger.info(f"Orders synchronisatie voltooid: {synced_count} orders opgeslagen.")
        return synced_count

    # --------------------------------------------------------------------------
    # 4. Nieuwe Order Aanmaken
    # --------------------------------------------------------------------------
    def create_order(self, customer_number: str, customer_name: str, order_date: str,
                     delivery_date: str, reference: str, items: list) -> dict:
        """
        Maakt een nieuwe order aan in Silvasoft en slaat deze direct lokaal op.
        items: [{"article_number": "12418", "quantity": 2, "name": "...", "short_name": "...", "price": 62.48}]
        """
        if not items:
            raise ValueError("Selecteer ten minste één product.")

        # Converteer datums naar DD-MM-YYYY voor Silvasoft
        nl_order_date = self._format_nl_date(order_date)
        nl_delivery_date = self._format_nl_date(delivery_date)

        order_lines = []
        for item in items:
            qty = int(item.get("quantity") or 0)
            if qty <= 0:
                continue
            line_data = {
                "ProductNumber": str(item.get("article_number")),
                "Quantity": qty,
                "Description": item.get("name") or "",
                "DeliveryDate": nl_delivery_date,
                "UseArticlePrice": True,
                "UseArticleDescription": True
            }
            order_lines.append(line_data)

        if not order_lines:
            raise ValueError("Er zijn geen geldige aantallen ingevuld.")

        payload = {
            "CustomerName": customer_name,
            "OrderDate": nl_order_date,
            "OrderReference": reference,
            "OrderStatus": "Bevestigd",
            "Order_Orderline": order_lines
        }
        if customer_number and str(customer_number).isdigit() and int(customer_number) > 0:
            payload["CustomerNumber"] = int(customer_number)

        logger.info(f"Nieuwe order insturen naar Silvasoft voor klant {customer_name}: {payload}")
        resp = self._request("POST", "addorder/", json_data=payload)
        logger.info(f"Silvasoft AddOrder response: {resp}")

        new_order_number = ""
        if isinstance(resp, dict):
            new_order_number = str(resp.get("OrderNumber") or resp.get("NewOrderNumber") or "")
        elif isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], dict):
            new_order_number = str(resp[0].get("OrderNumber") or resp[0].get("NewOrderNumber") or "")

        if not new_order_number or new_order_number == "0":
            err_detail = ""
            if isinstance(resp, dict):
                err_detail = resp.get("errorMessage") or resp.get("error") or str(resp)
            raise RuntimeError(f"Silvasoft heeft geen geldig ordernummer geretourneerd ({err_detail or 'Onbekende fout'}).")

        # Weeknummer en jaar berekenen voor het Kanban bord
        d_week, d_year = self._parse_week_and_year(nl_delivery_date)

        # Adres en contactpersoon bepalen
        street = unit = postal_code = city = contact_person = phone = ""
        if isinstance(resp, dict):
            addresses = resp.get("Order_Address") or []
            for addr in addresses:
                if addr.get("Address_Type") == "ShippingAddress":
                    street = (addr.get("Address_Street") or "").strip()
                    unit = (addr.get("Address_Unit") or "").strip()
                    postal_code = (addr.get("Address_PostalCode") or "").strip()
                    city = (addr.get("Address_City") or "").strip()
                    break
            if not street and addresses:
                first = addresses[0]
                street = (first.get("Address_Street") or "").strip()
                unit = (first.get("Address_Unit") or "").strip()
                postal_code = (first.get("Address_PostalCode") or "").strip()
                city = (first.get("Address_City") or "").strip()

            contacts = resp.get("Order_Contact") or []
            if contacts:
                fc = contacts[0]
                c_first = (fc.get("FirstName") or "").strip()
                c_last = (fc.get("LastName") or fc.get("FamilyName") or "").strip()
                contact_person = f"{c_first} {c_last}".strip()
                phone = str(fc.get("Phone") or "").strip()

        # Samenvatting bieren bouwen (bijv. "2x OG")
        summary_parts = []
        for it in items:
            q = int(it.get("quantity") or 0)
            if q > 0:
                s_name = it.get("short_name") or it.get("name") or "Bier"
                summary_parts.append(f"{q}x {s_name}")
        products_summary = ", ".join(summary_parts) if summary_parts else "Bier order"

        # Direct lokaal opslaan in de database zodat de order ALTIJD direct op het bord staat
        prefix = Config.DB_TABLE_PREFIX
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order_lines_json = json.dumps(order_lines)

        try:
            with get_db() as db:
                existing = db.fetchone(f"SELECT order_number FROM {prefix}orders WHERE order_number = %s", (new_order_number,))
                if existing:
                    db.execute(f"""
                        UPDATE {prefix}orders
                        SET customer_number = %s, customer_name = %s, contact_person = %s, phone = %s,
                            address_street = %s, address_unit = %s, address_postal_code = %s, address_city = %s,
                            order_date = %s, delivery_date = %s, delivery_week = %s, delivery_year = %s,
                            status = 'Bevestigd', reference = %s, products_summary = %s, order_lines_json = %s, updated_at = %s
                        WHERE order_number = %s
                    """, (customer_number, customer_name, contact_person, phone, street, unit, postal_code, city,
                          nl_order_date, nl_delivery_date, d_week, d_year, reference, products_summary, order_lines_json, now_str, new_order_number))
                else:
                    db.execute(f"""
                        INSERT INTO {prefix}orders (
                            order_number, customer_number, customer_name, contact_person, phone,
                            address_street, address_unit, address_postal_code, address_city,
                            order_date, delivery_date, delivery_week, delivery_year,
                            status, reference, products_summary, order_lines_json, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (new_order_number, customer_number, customer_name, contact_person, phone,
                          street, unit, postal_code, city, nl_order_date, nl_delivery_date, d_week, d_year,
                          "Bevestigd", reference, products_summary, order_lines_json, now_str, now_str))
            logger.info(f"Order #{new_order_number} direct lokaal opgeslagen in database.")
        except Exception as e:
            logger.error(f"Fout bij direct lokaal opslaan van order #{new_order_number}: {e}")

        return {
            "success": True,
            "order_number": new_order_number,
            "customer_name": customer_name,
            "delivery_date": nl_delivery_date,
            "reference": reference,
            "message": f"Order #{new_order_number} succesvol aangemaakt in Silvasoft!"
        }

    # --------------------------------------------------------------------------
    # 5. Order Status Wijzigen naar "Geleverd"
    # --------------------------------------------------------------------------
    def mark_order_delivered(self, order_number: str) -> dict:
        """Zet de status van een order in Silvasoft op 'Geleverd'."""
        if not order_number or order_number == "0":
            raise ValueError("Ongeldig ordernummer.")

        num_int = int(order_number) if order_number.isdigit() else order_number
        payload = {
            "OrderNumber": num_int,
            "OrderStatus": "Geleverd"
        }

        logger.info(f"Order #{order_number} bijwerken naar status 'Geleverd' in Silvasoft...")
        self._request("PUT", "updateorder/", json_data=payload)

        # Lokaal direct updaten in de database
        prefix = Config.DB_TABLE_PREFIX
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as db:
            db.execute(f"""
                UPDATE {prefix}orders
                SET status = 'Geleverd', updated_at = %s
                WHERE order_number = %s
            """, (now_str, order_number))

        logger.info(f"Order #{order_number} succesvol gemarkeerd als 'Geleverd'.")
        return {"success": True, "order_number": order_number, "status": "Geleverd"}

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------
    def _format_nl_date(self, date_str: str) -> str:
        """Converteert YYYY-MM-DD, DD-MM-YYYY of DD-MM naar DD-MM-YYYY."""
        if not date_str:
            return datetime.datetime.now().strftime("%d-%m-%Y")
        date_str = str(date_str).strip()
        if "-" in date_str or "/" in date_str:
            sep = "-" if "-" in date_str else "/"
            parts = [p.strip() for p in date_str.split(sep)]
            if len(parts) == 3:
                if len(parts[0]) == 4:  # YYYY-MM-DD
                    return f"{int(parts[2]):02d}-{int(parts[1]):02d}-{parts[0]}"
                else:  # DD-MM-YYYY
                    return f"{int(parts[0]):02d}-{int(parts[1]):02d}-{parts[2]}"
            elif len(parts) == 2:  # DD-MM -> voeg huidig jaar toe
                cur_year = datetime.datetime.now().year
                return f"{int(parts[0]):02d}-{int(parts[1]):02d}-{cur_year}"
        return datetime.datetime.now().strftime("%d-%m-%Y")

    def _parse_week_and_year(self, date_str: str) -> tuple:
        """Berekent weeknummer en jaar uit een datumaanduiding."""
        if not date_str:
            today = datetime.date.today()
            return today.isocalendar()[1], today.year

        clean = str(date_str).strip()
        try:
            if "-" in clean or "/" in clean:
                sep = "-" if "-" in clean else "/"
                parts = [p.strip() for p in clean.split(sep)]
                if len(parts) == 3:
                    if len(parts[0]) == 4:
                        dt = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                    else:
                        dt = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
                    iso = dt.isocalendar()
                    return iso[1], iso[0]
                elif len(parts) == 2:
                    cur_year = datetime.date.today().year
                    dt = datetime.date(cur_year, int(parts[1]), int(parts[0]))
                    iso = dt.isocalendar()
                    return iso[1], iso[0]
        except Exception:
            pass

        today = datetime.date.today()
        return today.isocalendar()[1], today.year


# Singleton instance
silvasoft_client = SilvasoftClient()
