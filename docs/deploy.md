# Deployment (staging)

Live at https://vesha.onrender.com. The whole site is behind a shared staging login while the
on-screen SMS code is switched on; the login is set in Render as `TWIRL_BASIC_AUTH`.

| Piece | Where | Notes |
|---|---|---|
| Web app | Render, workspace "Twirl", service `vesha` (free, Frankfurt) | Docker build from `main`; deploys on every push. Migrations run on start |
| Database | Neon project "Twirl" (`noisy-sun-01705977`), branch `br-dark-night-b1af8w2l`, Frankfurt | Postgres 18 with `btree_gist` (double-booking guard). App uses the direct (unpooled) host |
| Photos | Neon Object Storage, bucket `photos` on the same branch | App credential `vesha-render-app` (storage read/write). Served through `/media/...` |
| Background jobs | Neon Function `vesharun` + schedule trigger every 10 min | Calls `POST /internal/jobs` with `TWIRL_CRON_SECRET`; also keeps the free Render instance awake. Source: `ops/neon-cron/index.mjs` |

## Settings (Render → vesha → Environment)

`TWIRL_DATABASE_URL`, `TWIRL_SECRET_KEY`, `TWIRL_BASE_URL`, `TWIRL_HTTPS_ONLY=true`,
`TWIRL_STORAGE_BACKEND=s3`, `TWIRL_S3_ENDPOINT_URL`, `TWIRL_S3_BUCKET=photos`, `TWIRL_S3_REGION=eu-central-1`,
`TWIRL_S3_ACCESS_KEY_ID`, `TWIRL_S3_SECRET_ACCESS_KEY`, `TWIRL_CRON_SECRET`, `TWIRL_RUN_SCHEDULER=true`,
`TWIRL_SMS_DEV_ECHO=true` (staging only), `TWIRL_BASIC_AUTH` (staging only).
Still empty: `TWIRL_TELEGRAM_BOT_TOKEN`, `TWIRL_TELEGRAM_ADMIN_CHAT_ID`, `TWIRL_SMTP_*`.

## Before real users

1. Connect an SMS provider, then set `TWIRL_SMS_DEV_ECHO=false` and remove `TWIRL_BASIC_AUTH`.
2. Telegram bot token + chat id for admin alerts.
3. Own domain (Render → Custom domains), then update `TWIRL_BASE_URL`.
4. Rotate the Neon database password and the storage credential if they were ever shared.
