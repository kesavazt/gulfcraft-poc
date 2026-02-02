#!/usr/bin/env python
import sys
import os
import time

sys.path.insert(0, '/home/site/wwwroot')

print("[WebJob] Starting Email Monitor...")
from backend.services.email_monitor import get_email_monitor

monitor = get_email_monitor()
monitor.start()

print("[WebJob] Email monitor started")
try:
    while True:
        time.sleep(60)
        print(f"[WebJob] Running... {time.strftime('%Y-%m-%d %H:%M:%S')}")
except KeyboardInterrupt:
    print("[WebJob] Shutting down...")
    monitor.stop()
