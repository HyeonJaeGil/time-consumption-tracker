# time_consumption_tracker/__init__.py
"""
Time Consumption Tracker (Loguru-like global instance)

Usage:
    from time_consumption_tracker import time_tracker

    time_tracker.add(sys.stdout)             # console sink
    time_tracker.add("logs/timing.log")      # file sink (path or directory)
    time_tracker.configure(emit_each=True)   # emit a line for each completed task

    with time_tracker("LOAD_DATA"):
        ...

    time_tracker.summary()                   # prints summary to configured sinks
"""

from .tracker import TimeTracker

# Global, single tracker instance (like loguru.logger)
time_tracker = TimeTracker()

__all__ = ["TimeTracker", "time_tracker"]

