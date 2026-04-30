#!/usr/bin/env bash
set -euo pipefail

if ! command -v fly >/dev/null 2>&1; then
  echo "Fly CLI topilmadi. Avval o'rnating: https://fly.io/docs/flyctl/install/"
  exit 1
fi

echo "Fly.io login oynasi ochiladi..."
fly auth login

read -r -p "App nomi [akvutsavdo-bot]: " APP_NAME
APP_NAME=${APP_NAME:-akvutsavdo-bot}

read -r -p "BotFather bergan BOT_TOKEN ni kiriting: " BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
  echo "BOT_TOKEN majburiy. @BotFather dan token olib qayta ishga tushiring."
  exit 1
fi

read -r -p "Admin Telegram ID [8332077004]: " ADMIN_ID
ADMIN_ID=${ADMIN_ID:-8332077004}

read -r -p "Asosiy kanal username yoki ID [@Azizbekl2026]: " MAIN_CHANNEL_ID
MAIN_CHANNEL_ID=${MAIN_CHANNEL_ID:-@Azizbekl2026}

read -r -p "Checkout API key (bo'sh qoldirish mumkin): " CHECKOUT_API_KEY

if ! fly apps list | grep -q "^$APP_NAME[[:space:]]"; then
  fly apps create "$APP_NAME"
fi

python - <<PY
from pathlib import Path
p = Path("fly.toml")
s = p.read_text()
s = s.replace("app = 'akvutsavdo-bot'", "app = '$APP_NAME'")
p.write_text(s)
PY

fly volumes create botdata --app "$APP_NAME" --region fra --size 1 --yes || true
fly secrets set --app "$APP_NAME" BOT_TOKEN="$BOT_TOKEN" ADMIN_ID="$ADMIN_ID" MAIN_CHANNEL_ID="$MAIN_CHANNEL_ID" CHECKOUT_API_KEY="$CHECKOUT_API_KEY"
fly deploy --app "$APP_NAME"

echo "✅ Deploy tugadi. Loglarni ko'rish: fly logs --app $APP_NAME"
