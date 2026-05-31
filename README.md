# FertilizerTracker

FertilizerTracker is a lightweight Flask app for tracking plant care with due dates, recurring tasks, photos, reminders, and basic account protection.

## What the app does

- Create and manage plants with:
  - Name, location, notes
  - Optional cover photo
  - Optional growth timeline photos with note + date
- Create care tasks per plant:
  - Activity name
  - Due date
  - Optional start/end window
  - Optional recurrence (daily, weekly, biweekly, monthly)
  - Optional email reminder timing (on due date or after due date)
- Complete tasks:
  - One-time tasks are marked complete
  - Recurring tasks automatically create the next occurrence (if still inside the configured date window)
- Archive plants while preserving task/photo history
- Review upcoming tasks on a dedicated view
- Configure SMTP and notification addresses from the in-app Settings page
- Send a test email from Settings
- Export/import JSON backups from built-in API endpoints

## Security and reliability updates included

- Login protection using `APP_USERNAME` and `APP_PASSWORD`
- Session secret is required (`SECRET_KEY`)
- CSRF validation for all state-changing requests
- Upload validation for image file types and image integrity checks
- Maximum upload size controlled by `MAX_CONTENT_LENGTH`
- SQLite auto-migration helpers add newly introduced columns on startup

## Quick start (Docker)

1. Set required environment values (example):

```bash
export SECRET_KEY='replace-with-a-long-random-value'
export APP_USERNAME='admin'
export APP_PASSWORD='change-me'
export SMTP_PASSWORD='smtp-password-if-needed'
```

2. Start the app:

```bash
docker compose up --build -d
```

3. Open it on your LAN:

- `http://<your-linux-server-ip>:8000`

## Environment variables

### Required

- `SECRET_KEY` - Flask session/signing secret
- `APP_USERNAME` - login username
- `APP_PASSWORD` - login password

### Optional

- `DATABASE_URL` - defaults to local SQLite file in `data/plants.db`
- `MAX_CONTENT_LENGTH` - max upload payload in bytes (default `5242880`, 5 MB)

### Optional email defaults/fallbacks

Settings page values are used first; if blank, these env vars are used:

- `NOTIFY_EMAIL_TO`
- `NOTIFY_EMAIL_FROM`
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD` (kept only in env, never stored in DB)
- `SMTP_SENDER_NAME`
- `SMTP_HELO_IDENT`
- `SMTP_AUTH_MODE`
- `SMTP_SECURITY`
- `SMTP_TLS_METHOD`

## Email reminders

### Configure in-app

Use **Settings** to configure SMTP host, auth mode, TLS behavior, sender, and recipients. Use **Send Test Email** to verify connectivity.

### Run reminder job manually

```bash
docker compose --profile email run --rm mailer
```

### Optional cron (daily 7 AM)

```bash
0 7 * * * cd /path/to/FertilizerTracker && docker compose --profile email run --rm mailer >> "$HOME/fertilizer-tracker-mail.log" 2>&1
```

The cron job runs as the user who owns the crontab. Keep the log file in a location that user can write to, such as `$HOME`. Writing directly to `/var/log` requires separate administrator setup and will prevent the reminder command from running if permission is denied.

After adding the cron entry, confirm the scheduled run with:

```bash
tail -n 100 "$HOME/fertilizer-tracker-mail.log"
```

## Data and files

- SQLite database persists at `./data/plants.db`
- Uploaded photos are stored under `./static/uploads`
- Plant archive keeps historical records instead of deleting active history

## Developer notes

- App initializes schema at runtime and applies compatible SQLite column additions automatically.
- API backup endpoints:
  - `GET /api/export`
  - `POST /api/import`

## Network exposure note

If you need internet access beyond your LAN, place the app behind a reverse proxy with TLS.
