#!/usr/bin/env python
"""
WebJob entry point for email monitoring service.
Runs continuously in Azure App Service as a WebJob.

Finds the app directory (where core/, services/ etc. live) by locating
the virtual environment, then imports and starts the email monitor.
"""
import os
import shutil
import sys
import time


def find_app_dir():
    """Find the app directory where core/ lives."""
    # Method 1: Use VIRTUAL_ENV if set
    venv = os.environ.get("VIRTUAL_ENV")
    if venv and os.path.isdir(venv):
        candidate = os.path.dirname(venv)
        if os.path.isdir(os.path.join(candidate, "core")):
            return candidate

    # Method 2: Locate gunicorn binary on PATH
    gunicorn_path = shutil.which("gunicorn")
    if gunicorn_path:
        real_path = os.path.realpath(gunicorn_path)
        candidate = os.path.dirname(os.path.dirname(os.path.dirname(real_path)))
        if os.path.isdir(os.path.join(candidate, "core")):
            return candidate

    # Method 3: Search /tmp for antenv directories with app code
    if os.path.isdir("/tmp"):
        for entry in os.listdir("/tmp"):
            candidate = os.path.join("/tmp", entry)
            if os.path.isdir(os.path.join(candidate, "antenv")) and os.path.isdir(os.path.join(candidate, "core")):
                return candidate

    # Method 4: Check /home/site/wwwroot directly
    if os.path.isdir("/home/site/wwwroot/core"):
        return "/home/site/wwwroot"

    return None


def main():
    print("[WebJob] Starting Email Monitor WebJob...", flush=True)
    print(f"[WebJob] Python version: {sys.version}", flush=True)
    print(f"[WebJob] Working directory: {os.getcwd()}", flush=True)

    app_dir = find_app_dir()
    if not app_dir:
        print("[WebJob] ERROR: Could not find app directory with core/ module", flush=True)
        sys.exit(1)

    print(f"[WebJob] Found app directory: {app_dir}", flush=True)

    # Add app directory to sys.path so imports work
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    os.chdir(app_dir)

    # Import and start the email monitor
    from services.email_monitor import get_email_monitor

    monitor = get_email_monitor()
    monitor.start()

    print("[WebJob] Email monitor started successfully", flush=True)

    # Keep the WebJob running
    try:
        while True:
            time.sleep(60)
            print(f"[WebJob] Still running... {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    except KeyboardInterrupt:
        print("[WebJob] Shutting down...", flush=True)
        monitor.stop()


if __name__ == "__main__":
    main()
