# ════════════════════════════════════════════
#  config.py — готовый конфиг, заполнен полностью
# ════════════════════════════════════════════

# ── Telegram ──────────────────────────────
BOT_TOKEN    = "8893092538:AAE8II2_GS3mOBTYQpCC_TRZMisD3medb7A"
BOT_NAME     = "VPN от Морти 😈"
BOT_USERNAME = "fb1VPNbot"
ADMIN_IDS    = [5670079010]

# ── Happ Proxy API ─────────────────────────
HAPP_PROVIDER_CODE = "9FhgY0Ee"
HAPP_AUTH_KEY      = "xDiZmHLcdQkJissNBf79ttuXryWH0Iib"
HAPP_DEVICE_LIMIT  = 5

# ── GitHub Pages (задеплоено) ──────────────
MINIAPP_URL  = "https://tmgjwwyt5h-debug.github.io/vpn-bot-web/miniapp"
SETUP_DOMAIN = "https://tmgjwwyt5h-debug.github.io/vpn-bot-web/setup"

# ── Поддержка ──────────────────────────────
SUPPORT_USERNAME = "rentxboxs"
SUPPORT_URL      = "https://t.me/rentxboxs"

# ── Оплата картой ──────────────────────────
SBER_CARD   = "2222 2222 2222 2222"
CARD_HOLDER = "Получатель"

# ── Оплата крипто (USDT TRC-20) ────────────
USDT_ADDRESS = "982729492249рв8"
USDT_RATE    = 90

# ── Реферальная программа ──────────────────
REFERRAL_BONUS_DAYS = 10

# ── Планы подписки ─────────────────────────
PLANS = [
    {"id":"month",   "name":"1 месяц",   "emoji":"📅", "price":199,  "days":30,  "label":"мес",   "description":"Идеально для старта"},
    {"id":"quarter", "name":"3 месяца",  "emoji":"💎", "price":499,  "days":90,  "label":"3 мес", "description":"Экономия 16%"},
    {"id":"half",    "name":"6 месяцев", "emoji":"🚀", "price":899,  "days":180, "label":"6 мес", "description":"Экономия 25%"},
    {"id":"year",    "name":"1 год",     "emoji":"👑", "price":1490, "days":365, "label":"год",   "description":"Максимальная выгода — 38%"},
]
