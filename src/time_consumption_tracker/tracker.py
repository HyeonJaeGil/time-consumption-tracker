# time_consumption_tracker/tracker.py
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

from loguru import Logger, logger as default_logger


@dataclass(frozen=True)
class TaskStats:
    task: str
    count: int
    total_s: float
    avg_s: float
    min_s: float
    max_s: float
    last_s: float


class _TaskContext:
    def __init__(self, tracker: "TimeTracker", task: str, level: Union[str, int]) -> None:
        self._tracker = tracker
        self._task = task
        self._level = level
        self._t0: Optional[float] = None

    def __enter__(self) -> "_TaskContext":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Always record time, even if exception occurs; don't swallow exceptions.
        t1 = time.perf_counter()
        t0 = self._t0 if self._t0 is not None else t1
        elapsed = max(0.0, t1 - t0)
        self._tracker._record(self._task, elapsed, level=self._level, exc_type=exc_type)
        return False


class TimeTracker:
    """
    Loguru-inspired time consumption tracker.

    Key features:
    - Global singleton-like usage via module-level `time_tracker`.
    - Context manager API: `with time_tracker("TASK", level="DEBUG")`.
    - Loguru-backed output: events and summaries are emitted through a configured Logger.
    - Summary output: task-wise total/avg/min/max/count.
    """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}
        self._logger: Logger = logger or default_logger

        # Behavior knobs
        self._emit_each: bool = False
        self._time_unit: str = "ms"          # "s" or "ms"
        self._include_timestamp: bool = True
        self._summary_level: Union[str, int] = "INFO"

    # ---------------------------
    # Public API
    # ---------------------------

    def __call__(self, task: str, *, level: Union[str, int] = "INFO") -> _TaskContext:
        """Return a context manager for the given task name and log level."""
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task name must be a non-empty string")
        if not isinstance(level, (str, int)):
            raise TypeError("level must be a loguru-compatible level (str or int)")
        return _TaskContext(self, task.strip(), level)

    def configure(
        self,
        *,
        emit_each: Optional[bool] = None,
        time_unit: Optional[str] = None,
        include_timestamp: Optional[bool] = None,
        summary_level: Optional[Union[str, int]] = None,
    ) -> "TimeTracker":
        """
        Configure tracker behavior.

        - emit_each: if True, emit a log-like line after every `with` block.
        - time_unit: "ms" or "s"
        - include_timestamp: prefix output with timestamp
        - summary_level: log level used when emitting summary
        """
        with self._lock:
            if emit_each is not None:
                self._emit_each = bool(emit_each)
            if time_unit is not None:
                if time_unit not in ("ms", "s"):
                    raise ValueError('time_unit must be "ms" or "s"')
                self._time_unit = time_unit
            if include_timestamp is not None:
                self._include_timestamp = bool(include_timestamp)
            if summary_level is not None:
                self._summary_level = summary_level
        return self

    def use_logger(self, logger: Logger) -> "TimeTracker":
        """Replace the underlying Loguru logger instance."""
        if not isinstance(logger, Logger):
            raise TypeError("logger must be a loguru.Logger instance")
        with self._lock:
            self._logger = logger
        return self

    def clear(self) -> None:
        """Clear all recorded task durations."""
        with self._lock:
            self._records.clear()

    def summary(
        self,
        *,
        sort_by: str = "total",
        descending: bool = True,
        limit: Optional[int] = None,
        reset: bool = False,
        title: str = "Time Consumption Summary",
    ) -> str:
        """
        Generate and emit a summary.

        Returns the rendered summary string (also emitted to the configured logger).
        sort_by: "total" | "avg" | "count" | "max" | "min" | "task"
        """
        stats = self._compute_stats()

        key_funcs = {
            "total": lambda s: s.total_s,
            "avg": lambda s: s.avg_s,
            "count": lambda s: s.count,
            "max": lambda s: s.max_s,
            "min": lambda s: s.min_s,
            "task": lambda s: s.task.lower(),
        }
        if sort_by not in key_funcs:
            raise ValueError(f"sort_by must be one of: {', '.join(key_funcs.keys())}")

        stats.sort(key=key_funcs[sort_by], reverse=descending)
        if limit is not None:
            stats = stats[: max(0, int(limit))]

        rendered = self._render_summary(stats, title=title)

        self._emit(rendered, level=self._summary_level)

        if reset:
            self.clear()

        return rendered

    # ---------------------------
    # Internal: recording + emit
    # ---------------------------

    def _record(self, task: str, elapsed_s: float, level: Union[str, int], exc_type: Optional[type] = None) -> None:
        with self._lock:
            self._records.setdefault(task, []).append(elapsed_s)

        if self._emit_each:
            msg = self._render_event(task, elapsed_s, level=level, exc_type=exc_type)
            self._emit(msg, level=level)

    def _emit(self, message: str, *, level: Union[str, int]) -> None:
        try:
            self._logger.log(level, message)
        except Exception:
            # don't let logging failures break the app
            pass

    # ---------------------------
    # Internal: formatting
    # ---------------------------

    def _fmt_time(self, seconds: float) -> str:
        if self._time_unit == "ms":
            return f"{seconds * 1000.0:.3f} ms"
        return f"{seconds:.6f} s"

    def _ts_prefix(self) -> str:
        if not self._include_timestamp:
            return ""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " | "

    def _render_event(self, task: str, elapsed_s: float, *, level: Union[str, int], exc_type: Optional[type]) -> str:
        ts = self._ts_prefix()
        status = "OK" if exc_type is None else f"EXC:{getattr(exc_type, '__name__', str(exc_type))}"
        return f"{ts}{level} | {status} | task={task} | elapsed={self._fmt_time(elapsed_s)}"

    def _compute_stats(self) -> List[TaskStats]:
        with self._lock:
            items = list(self._records.items())

        out: List[TaskStats] = []
        for task, durations in items:
            if not durations:
                continue
            total = float(sum(durations))
            count = int(len(durations))
            avg = total / count
            mn = float(min(durations))
            mx = float(max(durations))
            last = float(durations[-1])
            out.append(
                TaskStats(
                    task=task,
                    count=count,
                    total_s=total,
                    avg_s=avg,
                    min_s=mn,
                    max_s=mx,
                    last_s=last,
                )
            )
        return out

    def _render_summary(self, stats: List[TaskStats], *, title: str) -> str:
        ts = self._ts_prefix()
        lines: List[str] = []
        lines.append(f"{ts}{title}")
        lines.append("-" * max(24, len(title)))

        if not stats:
            lines.append("(no data)")
            return "\n".join(lines)

        # Table header
        header = f"{'TASK':30}  {'COUNT':>7}  {'TOTAL':>14}  {'AVG':>14}  {'MIN':>14}  {'MAX':>14}  {'LAST':>14}"
        lines.append(header)
        lines.append("-" * len(header))

        for s in stats:
            lines.append(
                f"{s.task[:30]:30}  "
                f"{s.count:7d}  "
                f"{self._fmt_time(s.total_s):>14}  "
                f"{self._fmt_time(s.avg_s):>14}  "
                f"{self._fmt_time(s.min_s):>14}  "
                f"{self._fmt_time(s.max_s):>14}  "
                f"{self._fmt_time(s.last_s):>14}"
            )

        # Footer totals
        grand_total = sum(s.total_s for s in stats)
        lines.append("-" * len(header))
        lines.append(f"{'TOTAL (all tasks)':30}  {'':7}  {self._fmt_time(grand_total):>14}")
        return "\n".join(lines)
