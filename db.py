import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DATABASE_PATH", "cap2an.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS merchants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    reward_target INTEGER NOT NULL DEFAULT 7,
    reward_name TEXT NOT NULL DEFAULT 'Gratis 1 produk',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loyalty_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    stamp_count INTEGER NOT NULL DEFAULT 0,
    rewards_available INTEGER NOT NULL DEFAULT 0,
    total_stamps INTEGER NOT NULL DEFAULT 0,
    total_rewards_redeemed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(merchant_id, customer_id),
    FOREIGN KEY(merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS action_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL CHECK(action IN ('cap','redeem')),
    merchant_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('stamp','reward_earned','redeem')),
    actor_telegram_user_id INTEGER,
    metadata TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(merchant_id) REFERENCES merchants(id) ON DELETE CASCADE,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_action_tokens_token ON action_tokens(token);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant_created ON transactions(merchant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_transactions_customer_created ON transactions(customer_id, created_at);
"""

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
