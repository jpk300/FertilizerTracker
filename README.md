# FertilizerTracker

A lightweight Flask web app for tracking outdoor plant upkeep tasks (fertilize, prune, mulch, etc.) with due-date reminders by email.

## Features
- Add plants with location/notes.
- Schedule maintenance activities with due dates.
- See overdue/due tasks on the dashboard.
- Mark tasks complete.
- Send email reminders for due tasks.

## Run on Linux with Docker
```bash
docker compose up --build -d
```

Then open from your phone or any device on the same network:
- `http://<your-linux-server-ip>:8000`

## Email reminders
1. Edit SMTP values in `docker-compose.yml`.
2. Run reminder job (manual trigger):
```bash
docker compose run --rm --profile email mailer
```

### Optional cron (daily at 7 AM)
On host server:
```bash
0 7 * * * cd /path/to/FertilizerTracker && docker compose run --rm --profile email mailer >> /var/log/fertilizer-tracker-mail.log 2>&1
```

## Notes
- Data is persisted at `./data/plants.db`.
- For internet/mobile access from outside your LAN, place behind reverse proxy + TLS.
