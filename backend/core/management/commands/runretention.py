"""Isolated service: the only process holding delete rights over the audit trail."""

import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from tickets.retention import run_retention


class Command(BaseCommand):
    help = "Apply the data retention policy once its schedule allows it"

    def handle(self, *args, **options):
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        heartbeat = Path("/tmp/pulse-retention-heartbeat")
        self.stdout.write("Retention service started.")
        while not stopping:
            heartbeat.touch()
            result = run_retention()
            if result:
                self.stdout.write(f"Retention applied: {result}")
            for _ in range(60):
                if stopping:
                    break
                time.sleep(1)
        heartbeat.unlink(missing_ok=True)
