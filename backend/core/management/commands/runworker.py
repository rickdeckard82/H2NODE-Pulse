"""Heartbeat and expiring identity challenges. Ticket notifications arrive in stage 5."""

import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

from core.identity_mail import cleanup, deliver_one


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
        self.stdout.write("Worker started; identity mail requires configured SMTP.")
        while not stopping:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            heartbeat.touch()
            cleanup()
            deliver_one()
            for _ in range(10):
                if stopping:
                    break
                time.sleep(1)
        heartbeat.unlink(missing_ok=True)
