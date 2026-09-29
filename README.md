# CAP2AN — Telegram-first MVP

CAP2AN adalah loyalty program gratis untuk merchant lokal. MVP ini memakai Telegram sebagai identity + customer channel agar pilot bisa jalan tanpa mobile app.

## Flow

### Customer
1. Buka `t.me/Cap2anBot` lalu `/start`.
2. Bot membuat loyalty card.
3. Tekan **Minta CAP** setelah transaksi.
4. Bot memberi one-time code yang berlaku beberapa menit.
5. Tunjukkan kode ke kasir.
6. Setelah target CAP tercapai, reward otomatis tersedia.
7. Tekan **Tukar Reward** untuk membuat one-time reward code.

### Merchant
Akun kasir/owner yang Telegram numeric user ID-nya ada di `MERCHANT_TELEGRAM_IDS` dapat memakai:

- `/cap CXXXXX` — validasi CAP customer.
- `/redeem RXXXXX` — redeem reward customer.
- `/stats` — statistik sederhana merchant.

One-time code mencegah customer menambah CAP sendiri dengan membagikan link statis.

## Menjalankan lokal

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Isi `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
MERCHANT_TELEGRAM_IDS=your_telegram_numeric_user_id
DEMO_MERCHANT_NAME=Kopi Demo
DEMO_MERCHANT_SLUG=demo
DEMO_REWARD_TARGET=7
DEMO_REWARD_NAME=Gratis 1 Kopi
DATABASE_PATH=cap2an.db
CAP_CODE_TTL_SECONDS=300
```

Lalu:

```bash
python bot.py
```

Bot memakai long polling sehingga cocok untuk laptop/VPS tanpa domain atau webhook pada fase pilot.

## Commands

Customer:
- `/start`
- `/card`
- `/history`
- `/delete_me`

Merchant:
- `/cap KODE`
- `/redeem KODE`
- `/stats`

## Security

- **Jangan commit bot token.** `.env` masuk `.gitignore`.
- CAP/reward codes one-time dan expired otomatis.
- Merchant commands hanya dapat dijalankan Telegram user ID yang di-whitelist.
- Customer dapat menghapus datanya dengan `/delete_me`.

## Next

- Multi-merchant onboarding + Telegram deep links.
- Merchant web dashboard + QR scanner.
- PostgreSQL production DB.
- BHP lead/reorder module.
- WhatsApp identity bila validasi bisnis sudah kuat.
