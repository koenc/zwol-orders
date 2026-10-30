import logging
import sqlite3
import datetime
from pathlib import Path
from contextlib import contextmanager
from app.config import Config

logger = logging.getLogger("zwol_orders")

_USE_SQLITE = False


def check_mariadb_connection():
    """Controleert of MariaDB bereikbaar is, anders schakelen we over op SQLite."""
    global _USE_SQLITE
    if _USE_SQLITE:
        return False
    if not Config.DB_HOST:
        _USE_SQLITE = True
        return False

    try:
        import pymysql
        conn = pymysql.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            connect_timeout=3,
            cursorclass=pymysql.cursors.DictCursor
        )
        conn.close()
        _USE_SQLITE = False
        logger.info(f"✅ Succesvol verbonden met MariaDB database '{Config.DB_NAME}' op {Config.DB_HOST}:{Config.DB_PORT}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Kon geen verbinding maken met MariaDB ({e}). Overschakelen op lokale SQLite fallback.")
        _USE_SQLITE = True
        return False


class DatabaseConnection:
    """Wrapper die zowel PyMySQL als SQLite uniforme methoden biedt."""
    def __init__(self, conn, is_sqlite=False):
        self.conn = conn
        self.is_sqlite = is_sqlite

    def execute(self, query, params=None):
        if self.is_sqlite:
            # Vertaal %s naar ? voor SQLite
            sqlite_query = query.replace("%s", "?")
            cur = self.conn.cursor()
            cur.execute(sqlite_query, params or ())
            return cur
        else:
            cur = self.conn.cursor()
            cur.execute(query, params or ())
            return cur

    def executemany(self, query, params_list):
        if self.is_sqlite:
            sqlite_query = query.replace("%s", "?")
            cur = self.conn.cursor()
            cur.executemany(sqlite_query, params_list)
            return cur
        else:
            cur = self.conn.cursor()
            cur.executemany(query, params_list)
            return cur

    def fetchall(self, query, params=None):
        cur = self.execute(query, params)
        if self.is_sqlite:
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        else:
            return cur.fetchall()

    def fetchone(self, query, params=None):
        cur = self.execute(query, params)
        if self.is_sqlite:
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            return cur.fetchone()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


@contextmanager
def get_db():
    """Context manager voor veilige database interactie."""
    global _USE_SQLITE
    prefix = Config.DB_TABLE_PREFIX

    if not _USE_SQLITE:
        try:
            import pymysql
            conn = pymysql.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                database=Config.DB_NAME,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            db = DatabaseConnection(conn, is_sqlite=False)
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            return
        except Exception as e:
            logger.warning(f"MariaDB fout tijdens runtime: {e}. Fallback naar SQLite.")
            _USE_SQLITE = True

    # SQLite fallback
    Config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(Config.SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    db = DatabaseConnection(conn, is_sqlite=True)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialiseert tabellen in MariaDB of SQLite."""
    check_mariadb_connection()
    prefix = Config.DB_TABLE_PREFIX

    with get_db() as db:
        if db.is_sqlite:
            # SQLite DDL
            db.execute(f"""
            CREATE TABLE IF NOT EXISTS {prefix}customers (
                customer_number TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                contact_person TEXT,
                email TEXT,
                phone TEXT,
                street TEXT,
                unit TEXT,
                postal_code TEXT,
                city TEXT,
                group_name TEXT,
                is_customer INTEGER DEFAULT 1,
                updated_at TEXT
            )
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS {prefix}products (
                article_number TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT,
                show_in_order_app INTEGER DEFAULT 1,
                category TEXT,
                price REAL DEFAULT 0.0,
                vat_percentage REAL DEFAULT 21.0,
                unit TEXT,
                updated_at TEXT
            )
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS {prefix}orders (
                order_number TEXT PRIMARY KEY,
                customer_number TEXT,
                customer_name TEXT,
                contact_person TEXT,
                phone TEXT,
                address_street TEXT,
                address_unit TEXT,
                address_postal_code TEXT,
                address_city TEXT,
                order_date TEXT,
                delivery_date TEXT,
                delivery_week INTEGER,
                delivery_year INTEGER,
                status TEXT DEFAULT 'Bevestigd',
                reference TEXT,
                products_summary TEXT,
                order_lines_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS {prefix}sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT,
                status TEXT,
                records_count INTEGER,
                message TEXT,
                created_at TEXT
            )
            """)
        else:
            # MariaDB DDL
            db.execute(f"""
            CREATE TABLE IF NOT EXISTS `{prefix}customers` (
                `customer_number` VARCHAR(50) NOT NULL,
                `name` VARCHAR(255) NOT NULL,
                `contact_person` VARCHAR(255) NULL,
                `email` VARCHAR(255) NULL,
                `phone` VARCHAR(50) NULL,
                `street` VARCHAR(255) NULL,
                `unit` VARCHAR(50) NULL,
                `postal_code` VARCHAR(20) NULL,
                `city` VARCHAR(100) NULL,
                `group_name` VARCHAR(100) NULL,
                `is_customer` TINYINT(1) DEFAULT 1,
                `updated_at` DATETIME NULL,
                PRIMARY KEY (`customer_number`),
                INDEX `idx_cust_name` (`name`),
                INDEX `idx_cust_city` (`city`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS `{prefix}products` (
                `article_number` VARCHAR(50) NOT NULL,
                `name` VARCHAR(255) NOT NULL,
                `short_name` VARCHAR(50) NULL,
                `show_in_order_app` TINYINT(1) DEFAULT 1,
                `category` VARCHAR(100) NULL,
                `price` DECIMAL(10, 2) DEFAULT 0.00,
                `vat_percentage` DECIMAL(5, 2) DEFAULT 21.00,
                `unit` VARCHAR(50) NULL,
                `updated_at` DATETIME NULL,
                PRIMARY KEY (`article_number`),
                INDEX `idx_prod_short` (`short_name`),
                INDEX `idx_prod_show` (`show_in_order_app`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS `{prefix}orders` (
                `order_number` VARCHAR(50) NOT NULL,
                `customer_number` VARCHAR(50) NULL,
                `customer_name` VARCHAR(255) NULL,
                `contact_person` VARCHAR(255) NULL,
                `phone` VARCHAR(50) NULL,
                `address_street` VARCHAR(255) NULL,
                `address_unit` VARCHAR(50) NULL,
                `address_postal_code` VARCHAR(20) NULL,
                `address_city` VARCHAR(100) NULL,
                `order_date` VARCHAR(20) NULL,
                `delivery_date` VARCHAR(20) NULL,
                `delivery_week` INT NULL,
                `delivery_year` INT NULL,
                `status` VARCHAR(50) DEFAULT 'Bevestigd',
                `reference` VARCHAR(255) NULL,
                `products_summary` TEXT NULL,
                `order_lines_json` LONGTEXT NULL,
                `created_at` DATETIME NULL,
                `updated_at` DATETIME NULL,
                PRIMARY KEY (`order_number`),
                INDEX `idx_order_status` (`status`),
                INDEX `idx_order_week` (`delivery_year`, `delivery_week`),
                INDEX `idx_order_date` (`delivery_date`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            db.execute(f"""
            CREATE TABLE IF NOT EXISTS `{prefix}sync_log` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `sync_type` VARCHAR(50) NOT NULL,
                `status` VARCHAR(50) NOT NULL,
                `records_count` INT DEFAULT 0,
                `message` TEXT NULL,
                `created_at` DATETIME NULL,
                INDEX `idx_sync_type` (`sync_type`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

        # Migratie check: voeg group_name toe indien tabel al bestond zonder deze kolom
        try:
            if db.is_sqlite:
                db.execute(f"ALTER TABLE {prefix}customers ADD COLUMN group_name TEXT;")
            else:
                db.execute(f"ALTER TABLE `{prefix}customers` ADD COLUMN `group_name` VARCHAR(100) NULL AFTER `city`;")
        except Exception:
            pass

    logger.info(f"Database tabellen met prefix '{prefix}' succesvol gecontroleerd/aangemaakt.")
