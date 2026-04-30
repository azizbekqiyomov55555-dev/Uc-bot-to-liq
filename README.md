# Akvutsavdo Bot — Fly.io uchun to'liq tuzatilgan ZIP (v5)

Bu paket Telegram botni Fly.io’da polling rejimida ishga tushirish uchun tayyor.

## Screenshotdagi xato sababi

Logda ko'ringan xato:

```text
RuntimeError: BOT_TOKEN topilmadi
```

Bot token Fly.io **Secrets** bo'limiga kiritilmagani uchun app qayta-qayta restart bo'lgan. v5 paketda app token yo'q bo'lsa endi restart loopga tushmaydi, lekin bot ishlashi uchun baribir `BOT_TOKEN` kiritilishi shart.

## Eng oson deploy

ZIP’ni oching, papkaga kiring va terminalda ishga tushiring:

```bash
chmod +x deploy.sh
./deploy.sh
```

Script quyidagilarni o'zi bajaradi:

- Fly.io login
- app yaratish
- `/data` uchun volume yaratish
- `BOT_TOKEN`, `ADMIN_ID`, `MAIN_CHANNEL_ID` secrets qo'yish
- deploy qilish

## Fly.io panel orqali tuzatish

Agar app allaqachon deploy qilingan bo'lsa:

1. Fly.io panelida appni oching.
2. **Secrets** bo'limiga kiring.
3. Quyidagilarni qo'shing:
   - `BOT_TOKEN` = @BotFather bergan token
   - `ADMIN_ID` = `8332077004`
   - `MAIN_CHANNEL_ID` = `@Azizbekl2026`
   - `CHECKOUT_API_KEY` = checkout kaliti, kerak bo'lmasa bo'sh qoldiring
4. Appni **Restart** qiling yoki terminalda deploy qiling.

## Qo'lda terminal buyruqlari

```bash
fly auth login
fly apps create akvutsavdo-bot
fly volumes create botdata --app akvutsavdo-bot --region fra --size 1 --yes
fly secrets set --app akvutsavdo-bot BOT_TOKEN="YANGI_BOTFATHER_TOKEN" ADMIN_ID="8332077004" MAIN_CHANNEL_ID="@Azizbekl2026"
fly deploy --app akvutsavdo-bot
```

## Muhim

- `fly.toml` ichida `[http_service]` yo'q — bu to'g'ri, chunki Telegram bot HTTP server emas, polling bilan ishlaydi.
- SQLite baza `/data/bot_database.db` da saqlanadi.
- `/data` Fly volume orqali saqlanadi, deploydan keyin baza o'chib ketmaydi.

## Tekshirish

```bash
fly logs --app akvutsavdo-bot
```

To'g'ri ishlasa logda `Bot ishga tushdi` chiqadi.

## ZIP ichidagi fayllar

- `main.py` — bot kodi
- `Dockerfile` — Fly.io build uchun
- `fly.toml` — polling bot uchun HTTP servicesiz sozlama
- `requirements.txt` — Python kutubxonalar
- `runtime.txt` — Python versiya belgisi
- `deploy.sh` — avtomatik deploy yordamchisi
