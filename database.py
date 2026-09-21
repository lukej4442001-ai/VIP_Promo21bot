import sqlite3
from datetime import datetime
from config import VIP_TIERS

DB_FILE = "vip_promo21.db"

def conn():
    c = sqlite3.connect(DB_FILE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    db = conn()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance INTEGER DEFAULT 0,
        total_earned INTEGER DEFAULT 0,
        last_claim TEXT,
        last_spin TEXT,
        streak INTEGER DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        referred_by INTEGER,
        joined TEXT,
        tasks_done TEXT DEFAULT '',
        banned INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        reward INTEGER,
        max_uses INTEGER DEFAULT 999999,
        uses INTEGER DEFAULT 0,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS code_redemptions (
        user_id INTEGER,
        code TEXT,
        used_at TEXT,
        PRIMARY KEY (user_id, code)
    );
    CREATE TABLE IF NOT EXISTS withdraws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        method TEXT,
        address TEXT,
        status TEXT DEFAULT 'pending',
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS tasks (
        user_id INTEGER,
        task_key TEXT,
        completed_at TEXT,
        PRIMARY KEY (user_id, task_key)
    );
    """)
    db.commit()
    db.close()

def get_user(user_id):
    db = conn()
    row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return row

def create_user(user_id, username, first_name, referred_by=None, welcome=100):
    db = conn()
    db.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, balance, total_earned, referred_by, joined)
        VALUES (?,?,?,?,?,?,?)
    """, (user_id, username, first_name, welcome, welcome, referred_by, datetime.utcnow().isoformat()))
    db.commit()
    db.close()

def update_user(user_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user_id]
    db = conn()
    db.execute(f"UPDATE users SET {cols} WHERE user_id=?", vals)
    db.commit()
    db.close()

def add_balance(user_id, amount):
    db = conn()
    db.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
               (amount, max(amount, 0), user_id))
    db.commit()
    db.close()

def get_vip_tier(total_earned):
    tier = VIP_TIERS[0]
    for t in VIP_TIERS:
        if total_earned >= t[1]:
            tier = t
    return tier

def top_users(limit=10):
    db = conn()
    rows = db.execute("SELECT user_id, first_name, balance FROM users ORDER BY balance DESC LIMIT ?",
                      (limit,)).fetchall()
    db.close()
    return rows

def create_code(code, reward, max_uses=999999):
    db = conn()
    try:
        db.execute("INSERT INTO promo_codes (code, reward, max_uses, created) VALUES (?,?,?,?)",
                   (code.upper(), reward, max_uses, datetime.utcnow().isoformat()))
        db.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    db.close()
    return ok

def redeem_code(user_id, code):
    code = code.upper()
    db = conn()
    row = db.execute("SELECT * FROM promo_codes WHERE code=?", (code,)).fetchone()
    if not row:
        db.close()
        return (False, "❌ Invalid promo code.")
    if row["uses"] >= row["max_uses"]:
        db.close()
        return (False, "❌ This code has reached max uses.")
    used = db.execute("SELECT 1 FROM code_redemptions WHERE user_id=? AND code=?",
                      (user_id, code)).fetchone()
    if used:
        db.close()
        return (False, "❌ You already redeemed this code.")
    db.execute("INSERT INTO code_redemptions (user_id, code, used_at) VALUES (?,?,?)",
               (user_id, code, datetime.utcnow().isoformat()))
    db.execute("UPDATE promo_codes SET uses=uses+1 WHERE code=?", (code,))
    db.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
               (row["reward"], row["reward"], user_id))
    db.commit()
    reward = row["reward"]
    db.close()
    return (True, reward)

def complete_task(user_id, task_key):
    db = conn()
    try:
        db.execute("INSERT INTO tasks (user_id, task_key, completed_at) VALUES (?,?,?)",
                   (user_id, task_key, datetime.utcnow().isoformat()))
        db.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    db.close()
    return ok

def task_done(user_id, task_key):
    db = conn()
    row = db.execute("SELECT 1 FROM tasks WHERE user_id=? AND task_key=?",
                     (user_id, task_key)).fetchone()
    db.close()
    return row is not None

def create_withdraw(user_id, amount, method, address):
    db = conn()
    cur = db.execute("INSERT INTO withdraws (user_id, amount, method, address, created) VALUES (?,?,?,?,?)",
                     (user_id, amount, method, address, datetime.utcnow().isoformat()))
    wid = cur.lastrowid
    db.commit()
    db.close()
    return wid

def get_withdraw(wid):
    db = conn()
    row = db.execute("SELECT * FROM withdraws WHERE id=?", (wid,)).fetchone()
    db.close()
    return row

def update_withdraw(wid, status):
    db = conn()
    db.execute("UPDATE withdraws SET status=? WHERE id=?", (status, wid))
    db.commit()
    db.close()

def all_users():
    db = conn()
    rows = db.execute("SELECT user_id FROM users").fetchall()
    db.close()
    return [r["user_id"] for r in rows]

def stats():
    db = conn()
    total_users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total_points = db.execute("SELECT COALESCE(SUM(balance),0) c FROM users").fetchone()["c"]
    total_withdraws = db.execute("SELECT COUNT(*) c FROM withdraws WHERE status='pending'").fetchone()["c"]
    db.close()
    return total_users, total_points, total_withdraws
