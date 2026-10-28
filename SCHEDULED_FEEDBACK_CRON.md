# Scheduled WhatsApp Feedback

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

Run every minute on Linux/cPanel (server timezone does not matter):

```cron
* * * * * cd /path/to/anand-jeweller-backend && /path/to/venv/bin/python scripts/send_scheduled_feedback.py --delay 1 >> logs/scheduled-feedback.log 2>&1
```

Remove the old `send_daily_feedback.py` midnight cron before enabling this job.

Changing `FEEDBACK_DELAY_HOURS` affects new registrations after the backend is
restarted. Existing records retain the date/time saved when they registered.
