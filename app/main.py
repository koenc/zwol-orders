import datetime
import json
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g

from app.config import Config
from app.database import init_db, get_db
from app.auth import login_required, get_current_user
from app.services.silvasoft_service import silvasoft_client

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("zwol_orders")

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY

NL_MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
NL_DAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]


def format_dutch_date(date_str: str) -> str:
    """Formatteert een datum naar 'Vr 31 okt'."""
    if not date_str:
        return ""
    try:
        parts = date_str.split("-")
        if len(parts[0]) == 4:  # YYYY-MM-DD
            d = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:  # DD-MM-YYYY
            d = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
        day_name = NL_DAYS[d.weekday()]
        month_name = NL_MONTHS[d.month - 1]
        return f"{day_name} {d.day} {month_name}"
    except Exception:
        return date_str


def get_week_label(year: int, week: int) -> str:
    """Geeft datumreeks van een week, bijv: '27 okt - 2 nov'."""
    try:
        start_date = datetime.date.fromisocalendar(year, week, 1)
        end_date = datetime.date.fromisocalendar(year, week, 7)
        s_m = NL_MONTHS[start_date.month - 1]
        e_m = NL_MONTHS[end_date.month - 1]
        if s_m == e_m:
            return f"{start_date.day} - {end_date.day} {e_m}"
        else:
            return f"{start_date.day} {s_m} - {end_date.day} {e_m}"
    except Exception:
        return ""


# ==============================================================================
# Pagina Routes
# ==============================================================================
@app.route("/")
@app.route("/board")
@login_required
def board():
    return render_template("board.html")


@app.route("/create")
@login_required
def create_order_page():
    return render_template("create.html")


@app.route("/login", methods=["GET"])
def login():
    if get_current_user():
        return redirect(url_for("board"))
    return render_template("login.html", error=None)


@app.route("/login", methods=["POST"])
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    allowed_domain = f"@{Config.AUTH_DOMAIN}"

    if not email.endswith(allowed_domain):
        error = f"Alleen e-mailadressen eindigend op {allowed_domain} hebben toegang."
        return render_template("login.html", error=error), 403

    name = email.split("@")[0].replace(".", " ").title()
    session["user"] = {"email": email, "name": name, "is_dev": False}
    logger.info(f"Gebruiker ingelogd: {email}")

    next_url = request.args.get("next") or url_for("board")
    return redirect(next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "app": "zwol-orders", "timestamp": datetime.datetime.now().isoformat()})


# ==============================================================================
# API Routes (JSON)
# ==============================================================================
@app.route("/api/orders", methods=["GET"])
@login_required
def api_get_orders():
    """Haalt alle orders op met status 'Bevestigd', gegroepeerd per week (100% uit lokale database)."""
    prefix = Config.DB_TABLE_PREFIX

    with get_db() as db:
        # Haal orders op met status Bevestigd
        query = f"""
            SELECT * FROM {prefix}orders
            WHERE status = 'Bevestigd'
            ORDER BY delivery_year ASC, delivery_week ASC, delivery_date ASC, order_number ASC
        """
        rows = db.fetchall(query)

    # Groepeer per (year, week)
    grouped = {}
    for r in rows:
        order = dict(r)
        # Parse order lines JSON
        lines_raw = order.get("order_lines_json")
        try:
            order["order_lines"] = json.loads(lines_raw) if lines_raw else []
        except Exception:
            order["order_lines"] = []

        order["delivery_date_formatted"] = format_dutch_date(order.get("delivery_date"))

        y = order.get("delivery_year") or datetime.date.today().year
        w = order.get("delivery_week") or datetime.date.today().isocalendar()[1]
        key = (y, w)

        if key not in grouped:
            grouped[key] = {
                "year": y,
                "week": w,
                "date_range_label": get_week_label(y, w),
                "orders": []
            }
        grouped[key]["orders"].append(order)

    # Sorteer op kalenderweek
    sorted_weeks = sorted(grouped.values(), key=lambda x: (x["year"], x["week"]))

    return jsonify({"success": True, "weeks": sorted_weeks, "total_orders": len(rows)})


@app.route("/api/orders/<order_number>", methods=["GET"])
@login_required
def api_get_order_detail(order_number):
    """Haalt alle details op van één order."""
    prefix = Config.DB_TABLE_PREFIX
    with get_db() as db:
        row = db.fetchone(f"SELECT * FROM {prefix}orders WHERE order_number = %s", (order_number,))

    if not row:
        return jsonify({"success": False, "error": "Order niet gevonden."}), 404

    order = dict(row)
    try:
        order["order_lines"] = json.loads(order.get("order_lines_json") or "[]")
    except Exception:
        order["order_lines"] = []

    order["delivery_date_formatted"] = format_dutch_date(order.get("delivery_date"))
    return jsonify({"success": True, "order": order})


@app.route("/api/orders/<order_number>/deliver", methods=["PUT"])
@login_required
def api_deliver_order(order_number):
    """Zet de order in Silvasoft en lokaal op 'Geleverd'."""
    try:
        res = silvasoft_client.mark_order_delivered(order_number)
        return jsonify({"success": True, "message": f"Order #{order_number} is succesvol gemarkeerd als Geleverd!"})
    except Exception as e:
        logger.error(f"Fout bij leveren order {order_number}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/products", methods=["GET"])
@login_required
def api_get_products():
    """Haalt alle bieren/artikelen op die in de app getoond mogen worden (100% uit lokale database)."""
    prefix = Config.DB_TABLE_PREFIX
    with get_db() as db:
        rows = db.fetchall(f"""
            SELECT article_number, name, short_name, category, price, vat_percentage, unit
            FROM {prefix}products
            WHERE show_in_order_app = 1
            ORDER BY name ASC
        """)

    return jsonify({"success": True, "products": rows})


@app.route("/api/customers", methods=["GET"])
@login_required
def api_search_customers():
    """Zoekt klanten op bedrijfsnaam of plaats voor autocomplete (100% uit lokale database)."""
    q = (request.args.get("q") or "").strip()
    prefix = Config.DB_TABLE_PREFIX

    with get_db() as db:
        if not q:
            rows = db.fetchall(f"SELECT * FROM {prefix}customers WHERE is_customer = 1 ORDER BY name ASC LIMIT 20")
        else:
            search_term = f"%{q}%"
            rows = db.fetchall(f"""
                SELECT * FROM {prefix}customers
                WHERE is_customer = 1 AND (name LIKE %s OR city LIKE %s OR contact_person LIKE %s)
                ORDER BY name ASC
                LIMIT 25
            """, (search_term, search_term, search_term))

    return jsonify({"success": True, "customers": rows})


@app.route("/api/orders", methods=["POST"])
@login_required
def api_create_order():
    """Maakt een nieuwe order aan in Silvasoft."""
    data = request.get_json() or {}
    customer_number = data.get("customer_number")
    customer_name = (data.get("customer_name") or "").strip()
    order_date = data.get("order_date")
    delivery_date = data.get("delivery_date")
    reference = (data.get("reference") or "").strip()
    items = data.get("items") or []

    if not customer_name:
        return jsonify({"success": False, "error": "Klantnaam is verplicht."}), 400
    if not items:
        return jsonify({"success": False, "error": "Geen producten geselecteerd."}), 400

    try:
        res = silvasoft_client.create_order(
            customer_number=customer_number,
            customer_name=customer_name,
            order_date=order_date,
            delivery_date=delivery_date,
            reference=reference,
            items=items
        )
        return jsonify(res)
    except Exception as e:
        logger.error(f"Fout bij aanmaken order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sync", methods=["POST"])
@login_required
def api_force_sync():
    """Voert een synchronisatie uit met Silvasoft met bescherming tegen het 15 req/uur API-limiet."""
    force = request.args.get("force") == "1"
    prefix = Config.DB_TABLE_PREFIX

    # Cooldown check: niet vaker dan 1x per 10 minuten synchroniseren om ruim onder 15 req/u te blijven
    if not force:
        with get_db() as db:
            last_sync = db.fetchone(f"""
                SELECT created_at FROM {prefix}sync_log 
                WHERE status = 'success' 
                ORDER BY id DESC LIMIT 1
            """)
            if last_sync and last_sync.get("created_at"):
                try:
                    c_time = datetime.datetime.strptime(str(last_sync["created_at"]), "%Y-%m-%d %H:%M:%S")
                    diff_mins = (datetime.datetime.now() - c_time).total_seconds() / 60.0
                    if diff_mins < 10.0:
                        wait_mins = max(1, int(10.0 - diff_mins))
                        return jsonify({
                            "success": True,
                            "skipped": True,
                            "message": f"Gegevens zijn recent bijgewerkt ({int(diff_mins)} min geleden). Om binnen het gratis Silvasoft limiet (15 req/uur) te blijven, kan over {wait_mins} min weer gesynchroniseerd worden."
                        })
                except Exception:
                    pass

    try:
        p_count = silvasoft_client.sync_products()
        c_count = silvasoft_client.sync_customers()
        o_count = silvasoft_client.sync_orders()
        msg = f"{p_count} bieren, {c_count} klanten, {o_count} orders bijgewerkt."
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        logger.error(f"Fout tijdens force sync: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def seed_database_if_empty():
    """Vult eenmalig de database bij eerste installatie als deze nog leeg is."""
    prefix = Config.DB_TABLE_PREFIX
    try:
        with get_db() as db:
            p_cnt = db.fetchone(f"SELECT COUNT(*) as cnt FROM {prefix}products")
            if not p_cnt or (p_cnt.get("cnt") or 0) == 0:
                logger.info("Database is nog leeg. Eenmalige initiële synchronisatie starten...")
                silvasoft_client.sync_products()
                silvasoft_client.sync_customers()
                silvasoft_client.sync_orders()
    except Exception as e:
        logger.warning(f"Initiële sync bij opstart overgeslagen/vertraagd: {e}")


# ==============================================================================
# Applicatie Initialisatie
# ==============================================================================
try:
    init_db()
    seed_database_if_empty()
    if not app.config.get("TESTING"):
        from app.scheduler import start_background_scheduler
        start_background_scheduler()
except Exception as e:
    logger.error(f"Fout bij applicatie initialisatie: {e}")


if __name__ == "__main__":
    logger.info(f"Start ZWOL Orders server op poort {Config.PORT}...")
    app.run(host="0.0.0.0", port=Config.PORT, debug=(Config.FLASK_ENV == "development"))
