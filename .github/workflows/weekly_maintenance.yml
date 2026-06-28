name: "Daily Signal — Weekly Maintenance"

on:
  schedule:
    - cron: "0 2 * * 6"    # 02:00 UTC = 09:00 WIB, Sabtu
  workflow_dispatch:

jobs:
  weekly_maintenance:
    name: "🔧 Weekly Maintenance"
    runs-on: ubuntu-latest
    timeout-minutes: 30

    # env di level JOB — diwarisi semua steps
    env:
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      APP_ENV: production
      LOG_LEVEL: INFO

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: "📦 Install"
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt
          python -c "import yfinance, pandas, numpy, supabase; print('✅ OK')"

      - name: "📁 Logs"
        run: mkdir -p logs

      - name: "🧹 DB Cleanup"
        run: python -m src.runner db_cleanup
        continue-on-error: true

      - name: "🌐 Refresh Universe"
        run: python -m src.runner refresh_universe
        continue-on-error: true

      - name: "🔬 Run Backtests"
        run: python -m src.runner run_backtests --limit 50
        continue-on-error: true
        timeout-minutes: 20

      - name: "📊 Weekly Report"
        run: python -m src.runner weekly_report
        continue-on-error: true
