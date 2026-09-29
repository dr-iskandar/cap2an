import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from db import connect, init_db, utcnow

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MERCHANT_IDS = {
    int(v.strip())
    for v in os.getenv("MERCHANT_TELEGRAM_IDS", "").split(",")
    if v.strip().isdigit()
}
MERCHANT_NAME = os.getenv("DEMO_MERCHANT_NAME", "Kopi Demo")
MERCHANT_SLUG = os.getenv("DEMO_MERCHANT_SLUG", "demo").lower().strip()
REWARD_TARGET = max(1, int(os.getenv("DEMO_REWARD_TARGET", "7")))
REWARD_NAME = os.getenv("DEMO_REWARD_NAME", "Gratis 1 Kopi")
CAP_TTL = max(60, int(os.getenv("CAP_CODE_TTL_SECONDS", "300")))

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("cap2an")


def is_merchant(user_id: int) -> bool:
    return user_id in MERCHANT_IDS


def ensure_demo_merchant():
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM merchants WHERE slug = ?",
            (MERCHANT_SLUG,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE merchants SET name=?, reward_target=?, reward_name=? WHERE id=?",
                (MERCHANT_NAME, REWARD_TARGET, REWARD_NAME, row["id"]),
            )
            return row["id"]

        cur = conn.execute(
            "INSERT INTO merchants(name, slug, reward_target, reward_name, created_at) VALUES(?,?,?,?,?)",
            (MERCHANT_NAME, MERCHANT_SLUG, REWARD_TARGET, REWARD_NAME, utcnow()),
        )
        return cur.lastrowid


def upsert_customer(update: Update) -> int:
    user = update.effective_user
    now = utcnow()

    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM customers WHERE telegram_user_id=?",
            (user.id,),
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE customers SET username=?, first_name=?, updated_at=? WHERE id=?",
                (user.username, user.first_name, now, row["id"]),
            )
            return row["id"]

        cur = conn.execute(
            "INSERT INTO customers(telegram_user_id, username, first_name, created_at, updated_at) VALUES(?,?,?,?,?)",
            (user.id, user.username, user.first_name, now, now),
        )
        return cur.lastrowid


def get_or_create_card(customer_id: int, merchant_id: int):
    now = utcnow()

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM loyalty_cards WHERE merchant_id=? AND customer_id=?",
            (merchant_id, customer_id),
        ).fetchone()

        if not row:
            conn.execute(
                "INSERT INTO loyalty_cards(merchant_id, customer_id, created_at, updated_at) VALUES(?,?,?,?)",
                (merchant_id, customer_id, now, now),
            )
            row = conn.execute(
                "SELECT * FROM loyalty_cards WHERE merchant_id=? AND customer_id=?",
                (merchant_id, customer_id),
            ).fetchone()

        return row


def render_card(card, merchant) -> str:
    target = merchant["reward_target"]
    stamps = max(0, min(card["stamp_count"], target))
    circles = "🔴" * stamps + "⚪" * (target - stamps)
    remaining = max(0, target - stamps)

    if remaining:
        progress = f"*{remaining} CAP lagi* → {merchant['reward_name']}"
    else:
        progress = f"🎁 Reward siap: *{merchant['reward_name']}*"

    reward_line = ""
    if card["rewards_available"]:
        reward_line = f"\n🎁 Reward tersedia: *{card['rewards_available']}*"

    return (
        f"☕ *{merchant['name']}*\n\n"
        f"{circles}\n"
        f"*{stamps} / {target} CAP*\n"
        f"{progress}{reward_line}\n\n"
        f"Total CAP kamu: {card['total_stamps']}"
    )


def customer_keyboard(card) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("🔴 Minta CAP", callback_data="request_cap")]]

    if card["rewards_available"] > 0:
        buttons.append(
            [InlineKeyboardButton("🎁 Tukar Reward", callback_data="request_redeem")]
        )

    buttons.append(
        [InlineKeyboardButton("🔄 Refresh Kartu", callback_data="refresh_card")]
    )
    return InlineKeyboardMarkup(buttons)


def generate_token(prefix: str) -> str:
    alphabet = string.ascii_uppercase + string.digits
    alphabet = (
        alphabet.replace("0", "")
        .replace("O", "")
        .replace("I", "")
        .replace("1", "")
    )
    return prefix + "".join(secrets.choice(alphabet) for _ in range(5))


def create_action_token(action: str, customer_id: int, merchant_id: int) -> str:
    prefix = "C" if action == "cap" else "R"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=CAP_TTL)
    ).isoformat()

    for _ in range(5):
        token = generate_token(prefix)
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO action_tokens(token, action, merchant_id, customer_id, expires_at, created_at) VALUES(?,?,?,?,?,?)",
                    (
                        token,
                        action,
                        merchant_id,
                        customer_id,
                        expires_at,
                        utcnow(),
                    ),
                )
            return token
        except Exception:
            continue

    raise RuntimeError("Gagal membuat token unik")


def find_merchant():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM merchants WHERE slug=?",
            (MERCHANT_SLUG,),
        ).fetchone()


def load_customer_card(telegram_user_id: int):
    with connect() as conn:
        merchant = conn.execute(
            "SELECT * FROM merchants WHERE slug=?",
            (MERCHANT_SLUG,),
        ).fetchone()

        customer = conn.execute(
            "SELECT * FROM customers WHERE telegram_user_id=?",
            (telegram_user_id,),
        ).fetchone()

        if not customer:
            return None, None, None

        card = conn.execute(
            "SELECT * FROM loyalty_cards WHERE merchant_id=? AND customer_id=?",
            (merchant["id"], customer["id"]),
        ).fetchone()

        return merchant, customer, card


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    merchant = find_merchant()
    customer_id = upsert_customer(update)
    card = get_or_create_card(customer_id, merchant["id"])

    text = (
        "👋 *Selamat datang di CAP2AN*\n"
        "Loyalty gratis. Nggak perlu install app lain.\n\n"
        + render_card(card, merchant)
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=customer_keyboard(card),
    )


async def card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    merchant = find_merchant()
    customer_id = upsert_customer(update)
    card = get_or_create_card(customer_id, merchant["id"])

    await update.message.reply_text(
        render_card(card, merchant),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=customer_keyboard(card),
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_id = upsert_customer(update)
    merchant = find_merchant()
    get_or_create_card(customer_id, merchant["id"])

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT action, created_at
            FROM transactions
            WHERE customer_id=? AND merchant_id=?
            ORDER BY id DESC
            LIMIT 10
            """,
            (customer_id, merchant["id"]),
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "Belum ada aktivitas CAP. Tekan /card untuk lihat kartu kamu."
        )
        return

    labels = {
        "stamp": "🔴 +1 CAP",
        "reward_earned": "🎉 Reward didapat",
        "redeem": "🎁 Reward ditukar",
    }

    lines = ["*10 aktivitas terakhir:*", ""]

    for row in rows:
        dt = (
            datetime.fromisoformat(row["created_at"])
            .astimezone()
            .strftime("%d %b %H:%M")
        )
        lines.append(f"{labels.get(row['action'], row['action'])} — {dt}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer = (
        "*Customer*\n"
        "/card — lihat kartu CAP\n"
        "/history — riwayat CAP\n"
        "/delete_me — hapus data pribadi\n"
    )

    merchant = ""
    if is_merchant(update.effective_user.id):
        merchant = (
            "\n*Merchant*\n"
            "/cap KODE — tambah CAP customer\n"
            "/redeem KODE — tukar reward\n"
            "/stats — statistik singkat\n"
        )

    await update.message.reply_text(
        customer + merchant,
        parse_mode=ParseMode.MARKDOWN,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    merchant, customer, card = load_customer_card(query.from_user.id)

    if not customer or not card:
        await query.edit_message_text(
            "Kartu belum ditemukan. Kirim /start dulu."
        )
        return

    if query.data == "refresh_card":
        await query.edit_message_text(
            render_card(card, merchant),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=customer_keyboard(card),
        )
        return

    if query.data == "request_cap":
        token = create_action_token(
            "cap",
            customer["id"],
            merchant["id"],
        )

        await query.message.reply_text(
            f"🔴 *Kode CAP kamu:* `{token}`\n\n"
            f"Tunjukkan ke kasir. Berlaku {CAP_TTL // 60} menit "
            "dan hanya bisa dipakai sekali.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if query.data == "request_redeem":
        if card["rewards_available"] <= 0:
            await query.message.reply_text(
                "Belum ada reward yang bisa ditukar."
            )
            return

        token = create_action_token(
            "redeem",
            customer["id"],
            merchant["id"],
        )

        await query.message.reply_text(
            f"🎁 *Kode reward:* `{token}`\n\n"
            f"Tunjukkan ke kasir. Berlaku {CAP_TTL // 60} menit "
            "dan hanya bisa dipakai sekali.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_merchant(update.effective_user.id):
        await update.message.reply_text(
            "Perintah ini hanya untuk merchant."
        )
        return

    if not context.args:
        await update.message.reply_text("Format: /cap KODE")
        return

    token = context.args[0].upper().strip()
    now = datetime.now(timezone.utc)

    notify_user_id = None
    result_text = ""

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM action_tokens WHERE token=? AND action='cap'",
            (token,),
        ).fetchone()

        if not row:
            result_text = "❌ Kode CAP tidak ditemukan."

        elif row["used_at"]:
            result_text = "❌ Kode CAP sudah pernah dipakai."

        elif datetime.fromisoformat(row["expires_at"]) < now:
            result_text = "⌛ Kode CAP sudah kedaluwarsa."

        else:
            merchant = conn.execute(
                "SELECT * FROM merchants WHERE id=?",
                (row["merchant_id"],),
            ).fetchone()

            customer = conn.execute(
                "SELECT * FROM customers WHERE id=?",
                (row["customer_id"],),
            ).fetchone()

            card = conn.execute(
                "SELECT * FROM loyalty_cards WHERE merchant_id=? AND customer_id=?",
                (row["merchant_id"], row["customer_id"]),
            ).fetchone()

            new_stamps = card["stamp_count"] + 1
            new_rewards = card["rewards_available"]
            earned = False

            if new_stamps >= merchant["reward_target"]:
                new_stamps = 0
                new_rewards += 1
                earned = True

            conn.execute(
                """
                UPDATE loyalty_cards
                SET stamp_count=?,
                    rewards_available=?,
                    total_stamps=total_stamps+1,
                    updated_at=?
                WHERE id=?
                """,
                (
                    new_stamps,
                    new_rewards,
                    utcnow(),
                    card["id"],
                ),
            )

            conn.execute(
                "UPDATE action_tokens SET used_at=? WHERE id=?",
                (utcnow(), row["id"]),
            )

            conn.execute(
                "INSERT INTO transactions(merchant_id, customer_id, action, actor_telegram_user_id, created_at) VALUES(?,?,?,?,?)",
                (
                    merchant["id"],
                    customer["id"],
                    "stamp",
                    update.effective_user.id,
                    utcnow(),
                ),
            )

            if earned:
                conn.execute(
                    "INSERT INTO transactions(merchant_id, customer_id, action, actor_telegram_user_id, created_at) VALUES(?,?,?,?,?)",
                    (
                        merchant["id"],
                        customer["id"],
                        "reward_earned",
                        update.effective_user.id,
                        utcnow(),
                    ),
                )

            notify_user_id = customer["telegram_user_id"]
            result_text = "✅ CAP berhasil!"

            if earned:
                result_text += (
                    f" Customer mendapat reward: "
                    f"{merchant['reward_name']} 🎉"
                )

    await update.message.reply_text(result_text)

    if notify_user_id and result_text.startswith("✅"):
        merchant, customer, card = load_customer_card(notify_user_id)

        await context.bot.send_message(
            chat_id=notify_user_id,
            text="*CAP! 🔴*\n\n" + render_card(card, merchant),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=customer_keyboard(card),
        )


async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_merchant(update.effective_user.id):
        await update.message.reply_text(
            "Perintah ini hanya untuk merchant."
        )
        return

    if not context.args:
        await update.message.reply_text("Format: /redeem KODE")
        return

    token = context.args[0].upper().strip()
    now = datetime.now(timezone.utc)

    notify_user_id = None
    result_text = ""

    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM action_tokens WHERE token=? AND action='redeem'",
            (token,),
        ).fetchone()

        if not row:
            result_text = "❌ Kode reward tidak ditemukan."

        elif row["used_at"]:
            result_text = "❌ Kode reward sudah pernah dipakai."

        elif datetime.fromisoformat(row["expires_at"]) < now:
            result_text = "⌛ Kode reward sudah kedaluwarsa."

        else:
            card = conn.execute(
                "SELECT * FROM loyalty_cards WHERE merchant_id=? AND customer_id=?",
                (row["merchant_id"], row["customer_id"]),
            ).fetchone()

            customer = conn.execute(
                "SELECT * FROM customers WHERE id=?",
                (row["customer_id"],),
            ).fetchone()

            if not card or card["rewards_available"] <= 0:
                result_text = "❌ Customer tidak punya reward aktif."

            else:
                conn.execute(
                    """
                    UPDATE loyalty_cards
                    SET rewards_available=rewards_available-1,
                        total_rewards_redeemed=total_rewards_redeemed+1,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        utcnow(),
                        card["id"],
                    ),
                )

                conn.execute(
                    "UPDATE action_tokens SET used_at=? WHERE id=?",
                    (
                        utcnow(),
                        row["id"],
                    ),
                )

                conn.execute(
                    "INSERT INTO transactions(merchant_id, customer_id, action, actor_telegram_user_id, created_at) VALUES(?,?,?,?,?)",
                    (
                        row["merchant_id"],
                        row["customer_id"],
                        "redeem",
                        update.effective_user.id,
                        utcnow(),
                    ),
                )

                notify_user_id = customer["telegram_user_id"]
                result_text = "✅ Reward berhasil ditukar."

    await update.message.reply_text(result_text)

    if notify_user_id and result_text.startswith("✅"):
        merchant, customer, card = load_customer_card(notify_user_id)

        await context.bot.send_message(
            chat_id=notify_user_id,
            text=(
                "🎁 *Reward berhasil ditukar!*\n\n"
                + render_card(card, merchant)
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=customer_keyboard(card),
        )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_merchant(update.effective_user.id):
        await update.message.reply_text(
            "Perintah ini hanya untuk merchant."
        )
        return

    merchant = find_merchant()

    with connect() as conn:
        customers = conn.execute(
            "SELECT COUNT(*) c FROM loyalty_cards WHERE merchant_id=?",
            (merchant["id"],),
        ).fetchone()["c"]

        stamps = conn.execute(
            "SELECT COUNT(*) c FROM transactions WHERE merchant_id=? AND action='stamp'",
            (merchant["id"],),
        ).fetchone()["c"]

        redeems = conn.execute(
            "SELECT COUNT(*) c FROM transactions WHERE merchant_id=? AND action='redeem'",
            (merchant["id"],),
        ).fetchone()["c"]

    await update.message.reply_text(
        f"📊 *{merchant['name']}*\n\n"
        f"Customer terdaftar: *{customers}*\n"
        f"Total CAP: *{stamps}*\n"
        f"Reward redeemed: *{redeems}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def delete_me_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    with connect() as conn:
        customer = conn.execute(
            "SELECT id FROM customers WHERE telegram_user_id=?",
            (user_id,),
        ).fetchone()

        if not customer:
            await update.message.reply_text(
                "Tidak ada data CAP2AN yang tersimpan untuk akun ini."
            )
            return

        conn.execute(
            "DELETE FROM customers WHERE id=?",
            (customer["id"],),
        )

    await update.message.reply_text(
        "Data CAP2AN kamu sudah dihapus dari database bot ini."
    )


def build_app() -> Application:
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN belum diisi. "
            "Salin .env.example menjadi .env lalu isi token."
        )

    init_db()
    ensure_demo_merchant()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("card", card_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cap", cap_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("delete_me", delete_me_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    return app


if __name__ == "__main__":
    application = build_app()
    logger.info("CAP2AN Telegram MVP running with long polling")
    application.run_polling(drop_pending_updates=False)
