import os
import asyncio
import logging
from decimal import Decimal, InvalidOperation

import asyncpg
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DATABASE_URL = os.environ["DATABASE_URL"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-this-secret")
WEBHOOK_PATH = f"/telegram/{WEBHOOK_SECRET}"

REFERRAL_BONUS = Decimal("5")
MIN_WITHDRAW = Decimal("100")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

async def db():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await db()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance NUMERIC(12,2) NOT NULL DEFAULT 0,
            referrals INTEGER NOT NULL DEFAULT 0,
            referred_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            amount NUMERIC(12,2) NOT NULL,
            method TEXT NOT NULL,
            account TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
    finally:
        await conn.close()

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 আমার Referral", callback_data="referrals"),
         InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="link"),
         InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("📋 Withdraw History", callback_data="history")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_pending")]
    ])

async def ensure_user(user, referrer_id=None):
    conn = await db()
    try:
        existing = await conn.fetchrow(
            "SELECT telegram_id FROM users WHERE telegram_id=$1", user.id
        )
        if existing:
            await conn.execute(
                "UPDATE users SET username=$2, first_name=$3 WHERE telegram_id=$1",
                user.id, user.username, user.first_name
            )
            return False

        valid_ref = None
        if referrer_id and referrer_id != user.id:
            row = await conn.fetchrow(
                "SELECT telegram_id FROM users WHERE telegram_id=$1", referrer_id
            )
            if row:
                valid_ref = referrer_id

        await conn.execute("""
            INSERT INTO users
            (telegram_id, username, first_name, balance, referrals, referred_by)
            VALUES ($1,$2,$3,$4,0,$5)
        """, user.id, user.username, user.first_name, REFERRAL_BONUS if valid_ref else Decimal("0"), valid_ref)

        if valid_ref:
            await conn.execute("""
                UPDATE users
                SET balance = balance + $1, referrals = referrals + 1
                WHERE telegram_id=$2
            """, REFERRAL_BONUS, valid_ref)
        return True
    finally:
        await conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
        except ValueError:
            pass
    new_user = await ensure_user(update.effective_user, referrer_id)

    text = (
        "🎉 স্বাগতম!\n\n"
        f"👥 প্রতি Referral = ৳{REFERRAL_BONUS}\n"
        f"💸 Minimum Withdraw = ৳{MIN_WITHDRAW}\n"
        "💳 Payment = বিকাশ / নগদ\n\n"
        "নিচের মেনু থেকে একটি অপশন বেছে নিন।"
    )
    if new_user and referrer_id and referrer_id != update.effective_user.id:
        text += f"\n\n✅ আপনার অ্যাকাউন্টে Referral Bonus যোগ হয়েছে: ৳{REFERRAL_BONUS}"
    await update.message.reply_text(text, reply_markup=main_keyboard())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "balance":
        conn = await db()
        try:
            row = await conn.fetchrow("SELECT balance FROM users WHERE telegram_id=$1", uid)
        finally:
            await conn.close()
        bal = row["balance"] if row else Decimal("0")
        await q.message.reply_text(f"💰 আপনার Balance: ৳{bal:.2f}", reply_markup=main_keyboard())

    elif q.data == "referrals":
        conn = await db()
        try:
            row = await conn.fetchrow(
                "SELECT referrals FROM users WHERE telegram_id=$1", uid
            )
        finally:
            await conn.close()
        await q.message.reply_text(
            f"👥 আপনার মোট Referral: {row['referrals'] if row else 0} জন",
            reply_markup=main_keyboard()
        )

    elif q.data == "link":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start={uid}"
        await q.message.reply_text(
            f"🔗 আপনার Referral Link:\n\n{link}\n\nএই লিংক বন্ধুদের পাঠান।",
            reply_markup=main_keyboard()
        )

    elif q.data == "withdraw":
        await q.message.reply_text(
            "💸 Withdraw করতে নিচের ফরম্যাটে পাঠান:\n\n"
            "`/withdraw 100 bkash 01XXXXXXXXX`\n"
            "অথবা\n"
            "`/withdraw 100 nagad 01XXXXXXXXX`\n\n"
            "Minimum Withdraw ৳100।",
            parse_mode="Markdown"
        )

    elif q.data == "history":
        conn = await db()
        try:
            rows = await conn.fetch("""
                SELECT amount, method, account, status, created_at
                FROM withdrawals WHERE telegram_id=$1
                ORDER BY id DESC LIMIT 10
            """, uid)
        finally:
            await conn.close()
        if not rows:
            await q.message.reply_text("📋 এখনো কোনো Withdraw Request নেই.", reply_markup=main_keyboard())
            return
        lines = ["📋 আপনার Withdraw History:\n"]
        for r in rows:
            lines.append(f"৳{r['amount']:.2f} | {r['method']} | {r['status']}")
        await q.message.reply_text("\n".join(lines), reply_markup=main_keyboard())

    elif q.data == "admin_stats" and uid == ADMIN_ID:
        conn = await db()
        try:
            total = await conn.fetchval("SELECT COUNT(*) FROM users")
            pending = await conn.fetchval("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
            paid = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'")
        finally:
            await conn.close()
        await q.message.reply_text(
            f"📊 Admin Statistics\n\n👤 Users: {total}\n⏳ Pending: {pending}\n💸 Approved Withdraw: ৳{paid}"
        )

    elif q.data == "admin_pending" and uid == ADMIN_ID:
        conn = await db()
        try:
            rows = await conn.fetch("""
                SELECT id, telegram_id, amount, method, account
                FROM withdrawals WHERE status='pending'
                ORDER BY id ASC LIMIT 20
            """)
        finally:
            await conn.close()
        if not rows:
            await q.message.reply_text("✅ Pending withdrawal নেই।")
            return
        for r in rows:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{r['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{r['id']}")
            ]])
            await q.message.reply_text(
                f"#{r['id']}\nUser: {r['telegram_id']}\nAmount: ৳{r['amount']}\n"
                f"Method: {r['method']}\nAccount: {r['account']}",
                reply_markup=kb
            )

    elif q.data.startswith(("approve:", "reject:")) and uid == ADMIN_ID:
        action, wid = q.data.split(":")
        wid = int(wid)
        conn = await db()
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT telegram_id, amount, status FROM withdrawals WHERE id=$1 FOR UPDATE", wid
                )
                if not row or row["status"] != "pending":
                    await q.message.reply_text("এই request ইতিমধ্যে process করা হয়েছে।")
                    return
                if action == "approve":
                    await conn.execute(
                        "UPDATE withdrawals SET status='approved' WHERE id=$1", wid
                    )
                    msg = "✅ আপনার Withdraw Request approved হয়েছে।"
                else:
                    await conn.execute(
                        "UPDATE withdrawals SET status='rejected' WHERE id=$1", wid
                    )
                    await conn.execute(
                        "UPDATE users SET balance=balance+$1 WHERE telegram_id=$2",
                        row["amount"], row["telegram_id"]
                    )
                    msg = "❌ আপনার Withdraw Request rejected হয়েছে এবং টাকা balance-এ ফেরত দেওয়া হয়েছে।"
            await context.bot.send_message(row["telegram_id"], msg)
            await q.message.reply_text(f"Done: #{wid} {action}")
        finally:
            await conn.close()

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(context.args) != 3:
        await update.message.reply_text(
            "ফরম্যাট:\n/withdraw 100 bkash 01XXXXXXXXX\nঅথবা\n/withdraw 100 nagad 01XXXXXXXXX"
        )
        return
    try:
        amount = Decimal(context.args[0])
    except InvalidOperation:
        await update.message.reply_text("সঠিক amount দিন।")
        return
    method = context.args[1].lower()
    account = context.args[2]
    if method not in ("bkash", "nagad"):
        await update.message.reply_text("Payment method শুধু bkash বা nagad হবে।")
        return
    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"Minimum Withdraw ৳{MIN_WITHDRAW}।")
        return

    conn = await db()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT balance FROM users WHERE telegram_id=$1 FOR UPDATE", uid
            )
            if not row or row["balance"] < amount:
                await update.message.reply_text(f"❌ আপনার পর্যাপ্ত balance নেই। বর্তমান balance: ৳{row['balance'] if row else 0}")
                return
            await conn.execute(
                "UPDATE users SET balance=balance-$1 WHERE telegram_id=$2", amount, uid
            )
            wid = await conn.fetchval("""
                INSERT INTO withdrawals (telegram_id, amount, method, account)
                VALUES ($1,$2,$3,$4) RETURNING id
            """, uid, amount, method, account)
    finally:
        await conn.close()

    await update.message.reply_text(
        f"✅ Withdraw Request #{wid} জমা হয়েছে।\n"
        f"Amount: ৳{amount}\nMethod: {method}\nAccount: {account}\n\n"
        "Admin যাচাই করে payment করবে।"
    )
    await context.bot.send_message(
        ADMIN_ID,
        f"🔔 নতুন Withdraw Request #{wid}\nUser: {uid}\nAmount: ৳{amount}\n"
        f"Method: {method}\nAccount: {account}\n\n/admin দিয়ে manage করুন।"
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ আপনি Admin নন।")
        return
    await update.message.reply_text("👨‍💼 Admin Panel", reply_markup=admin_keyboard())

@app.on_event("startup")
async def startup():
    await init_db()
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.bot.set_webhook(
        url=os.environ["WEBHOOK_URL"] + WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message", "callback_query"]
    )
    log.info("Bot started")

@app.on_event("shutdown")
async def shutdown():
    await tg_app.bot.delete_webhook()
    await tg_app.stop()
    await tg_app.shutdown()

@app.get("/")
async def root():
    return {"status": "ok", "bot": "running"}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != WEBHOOK_SECRET:
        return {"ok": False}
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("withdraw", withdraw))
tg_app.add_handler(CommandHandler("admin", admin))
tg_app.add_handler(CallbackQueryHandler(button))
