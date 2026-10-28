# Scheduled WhatsApp Feedback with PM2

Queue registration creates one individual WhatsApp feedback job. Its due time is
registration time plus `FEEDBACK_DELAY_HOURS`; user-facing times are shown in IST,
while database timestamps are stored in UTC.

```env
FEEDBACK_IMMEDIATE_SEND=false
FEEDBACK_DELAY_HOURS=5
```

Run the migration once after deployment:

```bash
python scripts/migrate_scheduled_feedback.py
```

Test without sending:

```bash
python scripts/send_scheduled_feedback.py --dry-run
```

Start the continuous worker with PM2 (server timezone does not matter):

```bash
cd /path/to/anand-jeweller-backend
pm2 start /path/to/venv/bin/python --name anand-feedback-worker -- scripts/send_scheduled_feedback.py --daemon --interval 60 --delay 1
pm2 save
```

The worker checks every 60 seconds but sends only records whose `scheduled_at` is
due. Remove the old `send_daily_feedback.py` cron before enabling this process.

Useful commands:

```bash
pm2 status anand-feedback-worker
pm2 logs anand-feedback-worker --lines 100
pm2 restart anand-feedback-worker
```

Changing `FEEDBACK_DELAY_HOURS` affects new registrations after the backend is
restarted. Existing records retain the date/time saved when they registered.
