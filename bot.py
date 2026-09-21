import random
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

import config
from database import (
    init_db, get_user, create_user, update_user, add_balance,
    get_vip_tier, top_users, redeem_code, create_code,
    complete_task, task_done, create_withdraw, get_withdraw, update_withdraw,
    all_users, stats
)

# Conversation states
WITH_METHOD, WITH_AMOUNT, WITH_ADDRESS = range(3)

# ---------- HELPERS ----------
def cooldown_left(last_iso, hours):
    if not last_iso:
        return None
    last = datetime.fromisoformat(last_iso)
    nxt = last + timedelta(hours=hours)
    now = datetime.utcnow()
    if now >= nxt:
        return None
    d = nxt - now
    h, rem = divmod(int(d.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def fmt(n):
    return f"{n:,}"

def tier_badge(total_earned):
    tier = get_vip_tier(total_earned)
    return f"{tier[0]} ({tier[2]}x)"

async def is_joined(bot, user_id):
    if not config.FORCE_JOIN_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(config.FORCE_JOIN_CHANNEL, user_id)
        return member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER)
    except Exception:
        return True

def join_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=config.FORCE_JOIN_LINK or "https://t.me/")],
        [InlineKeyboardButton("✅ I Joined", callback_data="check_join")]
    ])

def main_menu():
    kb = [
        [InlineKeyboardButton("🎁 Claim Bonus", callback_data="claim"),
         InlineKeyboardButton("🎡 Spin", callback_data="spin")],
        [InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
         InlineKeyboardButton("🎟️ Promo Code", callback_data="promo")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("👥 Refer", callback_data="refer")],
        [InlineKeyboardButton("🔥 Streak", callback_data="streak"),
         InlineKeyboardButton("👑 VIP", callback_data="vip")],
        [InlineKeyboardButton("🏆 Top 10", callback_data="top"),
         InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

# ---------- /start ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    existing = get_user(u.id)
    ref_id = None
    if ctx.args and ctx.args[0].isdigit():
        ref_id = int(ctx.args[0])
        if ref_id == u.id:
            ref_id = None

    if not existing:
        create_user(u.id, u.username or "", u.first_name, referred_by=ref_id, welcome=config.WELCOME_BONUS)
        if ref_id:
            ref_user = get_user(ref_id)
            if ref_user and not ref_user["banned"]:
                add_balance(ref_id, config.REFERRAL_BONUS)
                update_user(ref_id, referrals=ref_user["referrals"] + 1)
                try:
                    await ctx.bot.send_message(
                        ref_id,
                        f"🎉 <b>New referral!</b>\n+{config.REFERRAL_BONUS} points added.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

    if not await is_joined(ctx.bot, u.id):
        await update.message.reply_text(
            "🔒 Please join our channel first to use the bot:",
            reply_markup=join_kb()
        )
        return

    user = get_user(u.id)
    text = (
        f"👋 Welcome <b>{u.first_name}</b> to <b>VIP_Promo21bot</b>!\n\n"
        f"💰 Balance: <b>{fmt(user['balance'])}</b> pts\n"
        f"🏅 Tier: <b>{tier_badge(user['total_earned'])}</b>\n"
        f"👥 Referrals: <b>{user['referrals']}</b>\n"
        f"🔥 Streak: <b>{user['streak']}</b>\n\n"
        f"Tap a button to begin 👇"
    )
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode=ParseMode.HTML)

# ---------- /claim ----------
async def claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not await is_joined(ctx.bot, u.id):
        return await _reply(update, "🔒 Join the channel first!", join_kb())

    user = get_user(u.id)
    if not user:
        create_user(u.id, u.username or "", u.first_name, welcome=0)
        user = get_user(u.id)

    left = cooldown_left(user["last_claim"], config.CLAIM_COOLDOWN_HOURS)
    if left:
        return await _reply(update, f"⏳ Already claimed.\nNext in <b>{left}</b>.")

    # Streak logic
    streak = user["streak"]
    if user["last_claim"]:
        last = datetime.fromisoformat(user["last_claim"])
        if datetime.utcnow() - last <= timedelta(hours=48):
            streak += 1
        else:
            streak = 1
    else:
        streak = 1

    base = random.randint(config.DAILY_BONUS_MIN, config.DAILY_BONUS_MAX)
    streak_mult = min(1 + (streak - 1) * 0.2, 3.0)  # cap 3x
    tier = get_vip_tier(user["total_earned"])
    reward = int(base * streak_mult * tier[2])

    add_balance(u.id, reward)
    update_user(u.id, last_claim=datetime.utcnow().isoformat(), streak=streak)

    # Award "claim" task
    if not task_done(u.id, "first_claim"):
        complete_task(u.id, "first_claim")

    msg = (
        f"🎁 <b>Bonus Claimed!</b>\n\n"
        f"Base: {base} pts\n"
        f"🔥 Streak: {streak} (x{streak_mult:.1f})\n"
        f"🏅 Tier: {tier[0]} (x{tier[2]})\n\n"
        f"💰 You earned: <b>+{fmt(reward)}</b> pts\n"
        f"New balance: <b>{fmt(get_user(u.id)['balance'])}</b>"
    )
    await _reply(update, msg, main_menu())

# ---------- /spin ----------
async def spin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    if not user:
        return await _reply(update, "Type /start first.")

    left = cooldown_left(user["last_spin"], config.SPIN_COOLDOWN_HOURS)
    if left:
        return await _reply(update, f"🎡 Spin cooldown.\nNext spin in <b>{left}</b>.")

    prize = random.choice(config.SPIN_PRIZES)
    tier = get_vip_tier(user["total_earned"])
    prize = int(prize * tier[2])
    add_balance(u.id, prize)
    update_user(u.id, last_spin=datetime.utcnow().isoformat())

    if not task_done(u.id, "first_spin"):
        complete_task(u.id, "first_spin")

    msg = (
        f"🎡 <b>Lucky Spin!</b>\n\n"
        f"🎯 You won: <b>+{fmt(prize)}</b> pts\n"
        f"💰 New balance: <b>{fmt(get_user(u.id)['balance'])}</b>"
    )
    await _reply(update, msg, main_menu())

# ---------- /promo ----------
async def promo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        code = ctx.args[0]
        u = update.effective_user
        ok, res = redeem_code(u.id, code)
        if ok:
            msg = f"🎟️ <b>Code Redeemed!</b>\n+{fmt(res)} pts\n💰 Balance: <b>{fmt(get_user(u.id)['balance'])}</b>"
        else:
            msg = res
        return await _reply(update, msg, main_menu())
    await _reply(update, "🎟️ Send a code like:\n<code>/promo VIP2025</code>")

# ---------- /tasks ----------
async def tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    tasks_list = [
        ("first_claim", "Claim your first daily bonus"),
        ("first_spin",  "Spin the lucky wheel once"),
        ("refer_1",     f"Refer {config.TASK_REFER_COUNT} friend"),
    ]
    lines = []
    kb_rows = []
    for key, desc in tasks_list:
        done = task_done(u.id, key)
        mark = "✅" if done else "⬜"
        lines.append(f"{mark} {desc}")
        if not done and key == "refer_1" and user["referrals"] >= config.TASK_REFER_COUNT:
            kb_rows.append([InlineKeyboardButton(f"🎁 Claim reward ({config.TASK_REWARD} pts)", callback_data="task_claim_refer_1")])
    text = "📋 <b>Daily Tasks</b>\n\n" + "\n".join(lines) + "\n\nComplete them for bonus points!"
    kb = InlineKeyboardMarkup(kb_rows + [[InlineKeyboardButton("⬅️ Back", callback_data="menu")]])
    await _reply(update, text, kb)

async def task_claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    user = get_user(u.id)
    if q.data == "task_claim_refer_1":
        if user["referrals"] >= config.TASK_REFER_COUNT and not task_done(u.id, "refer_1"):
            complete_task(u.id, "refer_1")
            add_balance(u.id, config.TASK_REWARD)
            await q.answer(f"+{config.TASK_REWARD} pts!", show_alert=True)
        else:
            await q.answer("Not eligible.", show_alert=True)

# ---------- /balance ----------
async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    if not user:
        return await _reply(update, "Type /start first.")
    tier = get_vip_tier(user["total_earned"])
    text = (
        f"💰 <b>Your Wallet</b>\n\n"
        f"Balance: <b>{fmt(user['balance'])}</b> pts\n"
        f"Total earned: <b>{fmt(user['total_earned'])}</b>\n"
        f"🏅 Tier: <b>{tier[0]}</b> ({tier[2]}x)\n"
        f"👥 Referrals: {user['referrals']}\n"
        f"🔥 Streak: {user['streak']}\n"
        f"📅 Joined: {user['joined'][:10]}"
    )
    await _reply(update, text, main_menu())

# ---------- /refer ----------
async def refer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    bot = await ctx.bot.get_me()
    link = f"https://t.me/{bot.username}?start={u.id}"
    text = (
        f"👥 <b>Invite & Earn</b>\n\n"
        f"Earn <b>{config.REFERRAL_BONUS}</b> pts per friend who joins!\n\n"
        f"🔗 <code>{link}</code>"
    )
    await _reply(update, text, main_menu())

# ---------- /streak ----------
async def streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    s = user["streak"]
    mult = min(1 + (s - 1) * 0.2, 3.0)
    text = (
        f"🔥 <b>Daily Streak</b>\n\n"
        f"Current: <b>{s} day(s)</b>\n"
        f"Multiplier: <b>x{mult:.1f}</b>\n\n"
        f"Claim daily to keep the streak alive!\n"
        f"Miss 48h = streak resets."
    )
    await _reply(update, text, main_menu())

# ---------- /vip ----------
async def vip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["👑 <b>VIP Tiers</b>\n"]
    for name, req, mult in config.VIP_TIERS:
        lines.append(f"{name} — requires {fmt(req)} total earned — bonus <b>x{mult}</b>")
    lines.append("\nEarn more to level up automatically!")
    await _reply(update, "\n".join(lines), main_menu())

# ---------- /top ----------
async def top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = top_users(10)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = ["🏆 <b>Top 10 Leaderboard</b>\n"]
    for i, r in enumerate(rows):
        name = r["first_name"] or "User"
        lines.append(f"{medals[i]} {name} — <b>{fmt(r['balance'])}</b> pts")
    await _reply(update, "\n".join(lines), main_menu())

# ---------- /withdraw ----------
async def withdraw_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = get_user(u.id)
    if user["balance"] < 1000:
        return await _reply(update, "💸 Minimum withdrawal: 1000 pts.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 UPI", callback_data="wm_upi")],
        [InlineKeyboardButton("🪙 Crypto", callback_data="wm_crypto")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu")],
    ])
    await _reply(update, "💸 Choose withdrawal method:", kb)
    return WITH_METHOD

async def withdraw_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["method"] = "UPI" if q.data == "wm_upi" else "Crypto"
    await q.message.reply_text(f"Enter amount in points (min 1000):")
    return WITH_AMOUNT

async def withdraw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number.")
        return WITH_AMOUNT
    user = get_user(update.effective_user.id)
    if amt < 1000 or amt > user["balance"]:
        await update.message.reply_text(f"❌ Amount must be between 1000 and {fmt(user['balance'])}.")
        return WITH_AMOUNT
    ctx.user_data["amount"] = amt
    await update.message.reply_text("Send your UPI ID or crypto wallet address:")
    return WITH_ADDRESS

async def withdraw_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    amount = ctx.user_data["amount"]
    method = ctx.user_data["method"]
    address = update.message.text.strip()

    user = get_user(u.id)
    if user["balance"] < amount:
        await update.message.reply_text("❌ Insufficient balance.")
        return ConversationHandler.END

    wid = create_withdraw(u.id, amount, method, address)
    update_user(u.id, balance=user["balance"] - amount)
    await update.message.reply_text(
        f"✅ <b>Withdrawal requested</b>\n\nID: <code>#{wid}</code>\nAmount: {fmt(amount)} pts\nMethod: {method}\nAddress: <code>{address}</code>\n\nStatus: pending admin approval.",
        parse_mode=ParseMode.HTML
    )
    if config.ADMIN_ID:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"wapp_{wid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wrej_{wid}")
        ]])
        try:
            await ctx.bot.send_message(
                config.ADMIN_ID,
                f"💸 New withdrawal #{wid}\nUser: {u.id}\nAmount: {fmt(amount)}\nMethod: {method}\nAddress: {address}",
                reply_markup=kb
            )
        except Exception:
            pass
    return ConversationHandler.END

# ---------- ADMIN ----------
async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    users, points, pending = stats()
    await update.message.reply_text(
        f"📊 <b>Admin Stats</b>\n\nUsers: {users}\nPoints in circulation: {fmt(points)}\nPending withdrawals: {pending}",
        parse_mode=ParseMode.HTML
    )

async def admin_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    if len(ctx.args) < 2:
        return await update.message.reply_text("Usage: /addcode CODE REWARD [MAXUSES]")
    code = ctx.args[0]
    try:
        reward = int(ctx.args[1])
        maxu = int(ctx.args[2]) if len(ctx.args) > 2 else 999999
    except ValueError:
        return await update.message.reply_text("Invalid numbers.")
    if create_code(code, reward, maxu):
        await update.message.reply_text(f"✅ Code <code>{code.upper()}</code> created — {reward} pts (max {maxu})", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Code already exists.")

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    if not ctx.args:
        return await update.message.reply_text("Usage: /broadcast message")
    msg = "📢 " + " ".join(ctx.args)
    ok, fail = 0, 0
    for uid in all_users():
        try:
            await ctx.bot.send_message(uid, msg)
            ok += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ Sent: {ok} | ❌ Failed: {fail}")

async def withdraw_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != config.ADMIN_ID:
        return await q.answer("Not authorized.", show_alert=True)
    await q.answer()
    data = q.data
    wid = int(data.split("_")[1])
    w = get_withdraw(wid)
    if not w or w["status"] != "pending":
        return await q.edit_message_text("Already processed.")

    if data.startswith("wapp"):
        update_withdraw(wid, "approved")
        await q.edit_message_text(f"✅ Withdrawal #{wid} APPROVED.")
        try:
            await ctx.bot.send_message(w["user_id"], f"✅ Your withdrawal #{wid} ({fmt(w['amount'])} pts) was approved!")
        except Exception:
            pass
    else:
        update_withdraw(wid, "rejected")
        add_balance(w["user_id"], w["amount"])  # refund
        await q.edit_message_text(f"❌ Withdrawal #{wid} REJECTED. Points refunded.")
        try:
            await ctx.bot.send_message(w["user_id"], f"❌ Your withdrawal #{wid} was rejected. Points refunded.")
        except Exception:
            pass

# ---------- HELP ----------
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ <b>Help</b>\n\n"
        "/start — Main menu\n"
        "/claim — Daily bonus (24h)\n"
        "/spin — Lucky wheel (12h)\n"
        "/tasks — Task missions\n"
        "/promo CODE — Redeem code\n"
        "/balance — Wallet\n"
        "/refer — Invite link\n"
        "/streak — Streak info\n"
        "/vip — VIP tiers\n"
        "/top — Leaderboard\n"
        "/withdraw — Cash out\n"
        "/help — This menu"
    )
    await _reply(update, text, main_menu())

# ---------- ROUTER ----------
async def _reply(update: Update, text: str, kb=None):
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    if d == "menu":
        user = get_user(q.from_user.id)
        await q.message.reply_text("🏠 Main menu:", reply_markup=main_menu())
    elif d == "claim":   await claim(update, ctx)
    elif d == "spin":    await spin(update, ctx)
    elif d == "tasks":   await tasks(update, ctx)
    elif d == "balance": await balance(update, ctx)
    elif d == "refer":   await refer(update, ctx)
    elif d == "streak":  await streak(update, ctx)
    elif d == "vip":     await vip(update, ctx)
    elif d == "top":     await top(update, ctx)
    elif d == "help":    await help_cmd(update, ctx)
    elif d == "promo":
        await q.message.reply_text("🎟️ Send a code like:\n<code>/promo VIP2025</code>", parse_mode=ParseMode.HTML)
    elif d == "check_join":
        if await is_joined(ctx.bot, q.from_user.id):
            await q.message.reply_text("✅ Verified! Send /start again.")
        else:
            await q.answer("❌ Not joined yet.", show_alert=True)
    elif d.startswith("task_claim_"):
        await task_claim(update, ctx)
    elif d.startswith("wapp_") or d.startswith("wrej_"):
        await withdraw_action(update, ctx)

# ---------- MAIN ----------
def main():
    init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_start)],
        states={
            WITH_METHOD: [CallbackQueryHandler(withdraw_method, pattern=r"^wm_")],
            WITH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITH_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_address)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("spin", spin))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("streak", streak))
    app.add_handler(CommandHandler("vip", vip))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("addcode", admin_code))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_button))

    print("VIP_Promo21bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
