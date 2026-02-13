"""
File Cleanup Manager

Manages lifecycle of temporary costing sheets.
Cleans up old files to prevent disk space accumulation.
"""

import os
import time
from typing import List
from core import config


class FileCleanupManager:
    """
    Manages lifecycle of temporary costing sheets and other generated files.

    Features:
    - Cleanup old files beyond retention period
    - Explicit cleanup for specific jobs
    - Safe file deletion with error handling
    """

    def __init__(self, temp_dir: str = None):
        """
        Initialize FileCleanupManager.

        Args:
            temp_dir: Directory containing temporary files (defaults to config.TEMP_DOWNLOADS_DIR)
        """
        self.temp_dir = temp_dir or config.TEMP_DOWNLOADS_DIR

        # Ensure directory exists
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            print(f"[FileCleanup] Created temp directory: {self.temp_dir}")

    def cleanup_old_files(self, days: int = 7) -> int:
        """
        Delete costing sheets older than N days.

        Args:
            days: Maximum age of files to keep (default: 7 days)

        Returns:
            int: Number of files deleted
        """
        if not os.path.exists(self.temp_dir):
            print(f"[FileCleanup] Temp directory does not exist: {self.temp_dir}")
            return 0

        cutoff_time = time.time() - (days * 86400)  # days * seconds_per_day
        deleted_count = 0

        try:
            for filename in os.listdir(self.temp_dir):
                # Only clean up costing sheets (pattern: costing_*.xlsx)
                if filename.startswith("costing_") and filename.endswith(".xlsx"):
                    filepath = os.path.join(self.temp_dir, filename)

                    # Check if file is older than cutoff
                    if os.path.isfile(filepath):
                        file_mtime = os.path.getmtime(filepath)
                        if file_mtime < cutoff_time:
                            try:
                                os.remove(filepath)
                                deleted_count += 1
                                print(f"[FileCleanup] Deleted old file: {filename}")
                            except OSError as e:
                                print(f"[FileCleanup] Error deleting {filename}: {e}")

            print(f"[FileCleanup] Cleanup complete: {deleted_count} files deleted (older than {days} days)")
            return deleted_count
        except Exception as e:
            print(f"[FileCleanup] Error during cleanup: {e}")
            return deleted_count

    def cleanup_job_files(self, job_id: str) -> bool:
        """
        Explicitly delete files for a specific job when approved/cancelled.

        Args:
            job_id: Costing job ID (e.g., "COST-12345678")

        Returns:
            bool: True if file was deleted, False otherwise
        """
        filename = f"costing_{job_id}.xlsx"
        filepath = os.path.join(self.temp_dir, filename)

        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"[FileCleanup] Deleted file for job {job_id}: {filename}")
                return True
            except OSError as e:
                print(f"[FileCleanup] Error deleting file for job {job_id}: {e}")
                return False
        else:
            print(f"[FileCleanup] File not found for job {job_id}: {filename}")
            return False

    def get_temp_files(self) -> List[dict]:
        """
        Get list of all temporary costing files with metadata.

        Returns:
            list: Files with name, size, and age information
        """
        if not os.path.exists(self.temp_dir):
            return []

        files = []
        current_time = time.time()

        try:
            for filename in os.listdir(self.temp_dir):
                if filename.startswith("costing_") and filename.endswith(".xlsx"):
                    filepath = os.path.join(self.temp_dir, filename)

                    if os.path.isfile(filepath):
                        file_stats = os.stat(filepath)
                        age_days = (current_time - file_stats.st_mtime) / 86400

                        files.append({
                            "filename": filename,
                            "job_id": filename.replace("costing_", "").replace(".xlsx", ""),
                            "size_bytes": file_stats.st_size,
                            "age_days": round(age_days, 2),
                            "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(file_stats.st_mtime))
                        })

            return files
        except Exception as e:
            print(f"[FileCleanup] Error listing temp files: {e}")
            return []

    def get_total_size(self) -> int:
        """
        Calculate total size of temporary files in bytes.

        Returns:
            int: Total size in bytes
        """
        if not os.path.exists(self.temp_dir):
            return 0

        total_size = 0

        try:
            for filename in os.listdir(self.temp_dir):
                if filename.startswith("costing_") and filename.endswith(".xlsx"):
                    filepath = os.path.join(self.temp_dir, filename)
                    if os.path.isfile(filepath):
                        total_size += os.path.getsize(filepath)

            return total_size
        except Exception as e:
            print(f"[FileCleanup] Error calculating total size: {e}")
            return 0

    def cleanup_all_files(self) -> int:
        """
        Delete ALL temporary costing files (use with caution).

        Returns:
            int: Number of files deleted
        """
        if not os.path.exists(self.temp_dir):
            return 0

        deleted_count = 0

        try:
            for filename in os.listdir(self.temp_dir):
                if filename.startswith("costing_") and filename.endswith(".xlsx"):
                    filepath = os.path.join(self.temp_dir, filename)
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                    except OSError as e:
                        print(f"[FileCleanup] Error deleting {filename}: {e}")

            print(f"[FileCleanup] Deleted all temporary files: {deleted_count} files removed")
            return deleted_count
        except Exception as e:
            print(f"[FileCleanup] Error during cleanup: {e}")
            return deleted_count
