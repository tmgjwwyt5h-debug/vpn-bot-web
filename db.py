from __future__ import annotations

import aiosqlite
from datetime import datetime, timedelta


class Database:
    def __init__(self, path: str = "vpn_bot.db"):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    referred_by INTEGER,
                    referral_bonus_days INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,
                    happ_key TEXT,
                    happ_key_id TEXT,
                    total_days INTEGER,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plan_id TEXT,
                    method TEXT,
                    amount INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def add_user(self, user_id: int, username: str, ref_id: int = None) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = await cursor.fetchone()
            if not exists:
                await db.execute(
                    "INSERT INTO users (user_id, username, referred_by) VALUES (?, ?, ?)",
                    (user_id, username, ref_id)
                )
                await db.commit()
                return True
            return False

    async def get_subscription(self, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d['expires_at'] = datetime.fromisoformat(d['expires_at']) if d['expires_at'] else None
                return d
            return None

    async def create_subscription(self, user_id: int, happ_key: str, days: int, key_id: str = None):
        expires = datetime.utcnow() + timedelta(days=days)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO subscriptions (user_id, happ_key, happ_key_id, total_days, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    happ_key=excluded.happ_key,
                    happ_key_id=excluded.happ_key_id,
                    total_days=excluded.total_days,
                    expires_at=excluded.expires_at
            """, (user_id, happ_key, key_id, days, expires.isoformat()))
            await db.commit()

    async def extend_subscription(self, user_id: int, days: int):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                current = datetime.fromisoformat(row[0])
                base = max(current, datetime.utcnow())
                new_exp = base + timedelta(days=days)
                await db.execute(
                    "UPDATE subscriptions SET expires_at = ?, total_days = total_days + ? WHERE user_id = ?",
                    (new_exp.isoformat(), days, user_id)
                )
                await db.commit()

    async def add_referral_bonus(self, user_id: int, days: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET referral_bonus_days = referral_bonus_days + ? WHERE user_id = ?",
                (days, user_id)
            )
            # Если есть подписка — сразу добавляем дни
            cursor = await db.execute(
                "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                current = datetime.fromisoformat(row[0])
                base = max(current, datetime.utcnow())
                new_exp = base + timedelta(days=days)
                await db.execute(
                    "UPDATE subscriptions SET expires_at = ? WHERE user_id = ?",
                    (new_exp.isoformat(), user_id)
                )
            await db.commit()

    async def get_referral_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_referral_bonus(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT referral_bonus_days FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_stats(self) -> dict:
        async with aiosqlite.connect(self.path) as db:
            c1 = await db.execute("SELECT COUNT(*) FROM users")
            users = (await c1.fetchone())[0]
            c2 = await db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE expires_at > ?",
                (datetime.utcnow().isoformat(),)
            )
            active = (await c2.fetchone())[0]
            today = datetime.utcnow().date().isoformat()
            c3 = await db.execute(
                "SELECT COUNT(*) FROM payments WHERE created_at >= ? AND status = 'approved'",
                (today,)
            )
            payments_today = (await c3.fetchone())[0]
            c4 = await db.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
            referrals = (await c4.fetchone())[0]
            return {"users": users, "active": active, "payments_today": payments_today, "referrals": referrals}

    async def get_all_users(self) -> list:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT u.user_id, u.username, s.expires_at FROM users u "
                "LEFT JOIN subscriptions s ON u.user_id = s.user_id "
                "ORDER BY u.created_at DESC LIMIT 20"
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['has_active_sub'] = (
                    d.get('expires_at') and
                    datetime.fromisoformat(d['expires_at']) > datetime.utcnow()
                ) if d.get('expires_at') else False
                result.append(d)
            return result
