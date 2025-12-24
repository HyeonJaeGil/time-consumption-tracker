# time_consumption_tracker/__init__.py
"""
Time Consumption Tracker (Loguru-like global instance)

Usage:
    from time_consumption_tracker import time_tracker

    from loguru import logger

    time_tracker.use_logger(logger)          # optional: set a specific loguru Logger
    time_tracker.configure(emit_each=True)   # emit a line for each completed task

    with time_tracker("LOAD_DATA", level="DEBUG"):
        ...

    time_tracker.summary()                   # prints summary via loguru
"""

from .tracker import TimeTracker

# Global, single tracker instance (like loguru.logger)
time_tracker = TimeTracker()

__all__ = ["TimeTracker", "time_tracker"]
