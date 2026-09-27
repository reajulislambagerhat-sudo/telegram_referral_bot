# Telegram Referral Bot

ফিচার:
- প্রতি Referral ৳5
- Minimum Withdraw ৳100
- bKash / Nagad
- Referral link
- Balance
- Referral count
- Withdraw request/history
- Admin approve/reject
- Admin statistics
- PostgreSQL database

## দরকার হবে
1. Telegram BotFather থেকে BOT_TOKEN
2. আপনার Telegram numeric ADMIN_ID
3. Supabase Free PostgreSQL-এর DATABASE_URL
4. Render Free Web Service

## Environment Variables
BOT_TOKEN = BotFather token
ADMIN_ID = আপনার Telegram numeric ID
DATABASE_URL = Supabase PostgreSQL connection string
WEBHOOK_URL = Render service URL, যেমন https://your-bot.onrender.com
WEBHOOK_SECRET = একটি গোপন অক্ষর/সংখ্যার string, যেমন MySecret_2026

## Render
GitHub-এ এই ফাইলগুলো আপলোড করে Render → New → Web Service থেকে repository connect করুন।
Build Command:
pip install -r requirements.txt

Start Command:
uvicorn app:app --host 0.0.0.0 --port $PORT

Plan: Free

তারপর Environment Variables বসিয়ে Deploy করুন।

## গুরুত্বপূর্ণ
Render Free Web Service idle হলে spin down করতে পারে; তাই এটি test/hobby ব্যবহারের জন্য উপযোগী। Free local filesystem persistent নয়, তাই এই bot-এর data PostgreSQL-এ রাখা হয়েছে।

Supabase-এ একটি Free project তৈরি করে PostgreSQL connection string নিয়ে DATABASE_URL হিসেবে দিন।

## নিরাপত্তা
BOT_TOKEN কখনো GitHub code-এ লিখবেন না। শুধু Render Environment Variables-এ রাখবেন।
