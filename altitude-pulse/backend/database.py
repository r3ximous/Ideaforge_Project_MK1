"""Small, transactional SQLite store; no database server required."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY AUTOINCREMENT,
 phone_number TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 access_token TEXT UNIQUE NOT NULL,
 loyalty_points INTEGER NOT NULL DEFAULT 0,
 tier TEXT NOT NULL DEFAULT 'Base' CHECK(tier IN ('Base','Gold','Platinum')),
 upgrade_month TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS menu_items (
 item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
 category TEXT NOT NULL CHECK(category IN ('Coffee','Tea','Cold Drinks','Pastry','Special')),
 price REAL NOT NULL CHECK(price >= 0), description TEXT NOT NULL,
 is_promo INTEGER NOT NULL DEFAULT 0, is_popular INTEGER NOT NULL DEFAULT 0,
 model_3d_url TEXT
);
CREATE TABLE IF NOT EXISTS orders (
 order_id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(user_id), customer_name TEXT NOT NULL,
 access_token TEXT UNIQUE NOT NULL,
 order_type TEXT NOT NULL CHECK(order_type IN ('takeaway','table')), table_number TEXT,
 subtotal_amount REAL NOT NULL, discount_amount REAL NOT NULL DEFAULT 0,
 total_amount REAL NOT NULL, points_earned INTEGER NOT NULL DEFAULT 0,
 payment_method TEXT NOT NULL, payment_status TEXT NOT NULL DEFAULT 'mock_paid',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','preparing','ready','completed','cancelled')),
 promo_token TEXT, used_upgrade INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), completed_at TEXT
);
CREATE TABLE IF NOT EXISTS order_items (
 order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
 order_id INTEGER NOT NULL REFERENCES orders(order_id),
 item_id INTEGER NOT NULL REFERENCES menu_items(item_id),
 item_name TEXT NOT NULL, item_size TEXT NOT NULL,
 customization TEXT NOT NULL DEFAULT '', price REAL NOT NULL,
 item_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS club_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, club_name TEXT NOT NULL,
 title TEXT NOT NULL, description TEXT NOT NULL, promo_code TEXT,
 discount_percent INTEGER NOT NULL DEFAULT 0, event_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_rsvps (
 user_id INTEGER NOT NULL REFERENCES users(user_id),
 event_id INTEGER NOT NULL REFERENCES club_events(event_id),
 token TEXT UNIQUE NOT NULL, discount_percent INTEGER NOT NULL,
 redeemed_order_id INTEGER REFERENCES orders(order_id),
 PRIMARY KEY(user_id,event_id)
);
CREATE TABLE IF NOT EXISTS order_logs (
 log_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(order_id),
 old_status TEXT, new_status TEXT NOT NULL, source TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_queue ON orders(status,created_at,order_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id,created_at);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @contextmanager
    def connect(self, write=False):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(SCHEMA)
