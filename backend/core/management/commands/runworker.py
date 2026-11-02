"""Persistent worker for identity mail, attachments and ticket notifications."""

import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

from core.identity_mail import cleanup, deliver_one
from tickets.attachments import scan_one
from tickets.notifications import check_one as integration_check
from tickets.notifications import deliver_one as deliver_ticket_notification
from tickets.reports import cleanup_exports
from tickets.sla import alert_breaches


class Command(BaseCommand):
    help = "Run heartbeat and configured identity mail delivery"

    def handle(self, *args, **options):
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        heartbeat = Path("/tmp/pulse-worker-heartbeat")
        self.stdout.write("Worker started; persistent notification delivery enabled.")
        last_sla = 0.0
        while not stopping:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            heartbeat.touch()
            cleanup()
            deliver_one()
            scan_one()
            integration_check()
            cleanup_exports()
            if time.monotonic() - last_sla >= 60:
                alert_breaches()
                last_sla = time.monotonic()
            # Bounded so identity mail, scans and the heartbeat keep running under backlog.
            for _ in range(20):
                if stopping or not deliver_ticket_notification():
                    break
            for _ in range(10):
                if stopping:
                    break
                time.sleep(1)
        heartbeat.unlink(missing_ok=True)
