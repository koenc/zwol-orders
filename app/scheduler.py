import threading
import time
import datetime
import logging
from app.services.silvasoft_service import silvasoft_client

logger = logging.getLogger("zwol_orders")

_SCHEDULER_THREAD = None
_STOP_EVENT = threading.Event()


def _background_sync_worker():
    """
    Achtergrond worker die periodiek synchroniseert binnen het 15 req/uur budget:
    - Elke 2 uur: orders ophalen (1 API request)
    - 1x per nacht (rond 03:30): klanten en producten verversen (~3 API requests)
    """
    logger.info("🕒 Achtergrond-scheduler voor Silvasoft gestart (laag-frequent, budget-vriendelijk).")

    last_order_sync = datetime.datetime.now()
    last_nightly_sync_date = None

    while not _STOP_EVENT.is_set():
        # Slaap in intervallen van 30 seconden zodat de thread snel kan stoppen
        for _ in range(60):
            if _STOP_EVENT.is_set():
                return
            time.sleep(30)

        now = datetime.datetime.now()

        # 1. Dagelijkse nachtelijke sync van stamgegevens (rond 03:30)
        if now.hour == 3 and now.minute >= 30 and last_nightly_sync_date != now.date():
            try:
                logger.info("🌙 Nachtelijke synchronisatie gestart (klanten & bieren)...")
                silvasoft_client.sync_products()
                silvasoft_client.sync_customers()
                silvasoft_client.sync_orders()
                last_nightly_sync_date = now.date()
                last_order_sync = now
                logger.info("🌙 Nachtelijke synchronisatie succesvol afgerond.")
            except Exception as e:
                logger.warning(f"Nachtelijke sync kon niet worden voltooid: {e}")
            continue

        # 2. Twee-uurs sync van openstaande orders
        time_since_order_sync = (now - last_order_sync).total_seconds()
        if time_since_order_sync >= 7200:  # 2 uur = 7200 seconden
            try:
                logger.info("🔄 Periodieke 2-uurs ordersync met Silvasoft gestart...")
                count = silvasoft_client.sync_orders()
                last_order_sync = now
                logger.info(f"🔄 Periodieke ordersync voltooid: {count} openstaande orders bijgewerkt.")
            except Exception as e:
                logger.warning(f"Periodieke ordersync uitgesteld: {e}")
                # Wacht 15 minuten voor een herpoging bij fout
                last_order_sync = now - datetime.timedelta(seconds=6300)


def start_background_scheduler():
    """Start de achtergrond scheduler thread eenmalig."""
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        return

    _STOP_EVENT.clear()
    _SCHEDULER_THREAD = threading.Thread(
        target=_background_sync_worker,
        name="SilvasoftSyncScheduler",
        daemon=True
    )
    _SCHEDULER_THREAD.start()
    logger.info("Achtergrond scheduler thread succesvol gestart.")


def stop_background_scheduler():
    """Stopt de achtergrond scheduler thread netjes."""
    _STOP_EVENT.set()
    if _SCHEDULER_THREAD is not None:
        _SCHEDULER_THREAD.join(timeout=2)
