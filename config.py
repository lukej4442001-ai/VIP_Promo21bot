import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Channel force-join (leave empty to disable)
FORCE_JOIN_CHANNEL = os.environ.get("FORCE_JOIN_CHANNEL", "")  # e.g. "@mychannel"
FORCE_JOIN_LINK = os.environ.get("FORCE_JOIN_LINK", "")

# Bonuses
WELCOME_BONUS = 100
DAILY_BONUS_MIN = 20
DAILY_BONUS_MAX = 100
CLAIM_COOLDOWN_HOURS = 24

SPIN_COOLDOWN_HOURS = 12
SPIN_PRIZES = [5, 10, 25, 50, 75, 100, 150, 250, 500]

REFERRAL_BONUS = 50
TASK_REFER_COUNT = 1
TASK_REWARD = 30

# VIP tiers: (name, min_balance_earned, multiplier)
VIP_TIERS = [
    ("🥉 Bronze",   0,      1.0),
    ("🥈 Silver",   500,    1.1),
    ("🥇 Gold",     2000,   1.25),
    ("💎 Platinum", 5000,   1.5),
    ("👑 Diamond",  10000,  2.0),
]
