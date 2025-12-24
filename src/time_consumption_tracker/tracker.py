# time_consumption_tracker/tracker.py
from __future__ import annotations

import os
import sys
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union, IO, Any


Sink = Callable[[str], None]
SinkTarget = Union[str, Path, IO[str], Sink]


@dataclass(frozen=True)
class TaskStats:
    task: str
    count: int
    total_s: float
    avg_s: float
    min_s: float
    max_s: float
    last_s: float


class _FileSink:
    def __init__(self, file_path: Union[str, Path], mode: str = "a", encoding: str = "utf-8") -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.file_path, mode=mode, encoding=encoding)

    def __call__(self, message: str) -> None:
        self._fh.write(message)
        if not message.endswith("\n"):
            self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class _StreamSink:
    def __init__(self, stream: IO[str]) -> None:
        self.stream = stream

    def __call__(self, message: str) -> None:
        self.stream.write(message)
        if not message.endswith("\n"):
            self.stream.write("\n")
        self.stream.flush()


class _TaskContext:
    def __init__(self, tracker: "TimeTracker", task: str) -> None:
        self._tracker = tracker
        self._task = task
        self._t0: Optional[float] = None

    def __enter__(self) -> "_TaskContext":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Always record time, even if exception occurs; don't swallow exceptions.
        t1 = time.perf_counter()
        t0 = self._t0 if self._t0 is not None else t1
        elapsed = max(0.0, t1 - t0)
        self._tracker._record(self._task, elapsed, exc_type=exc_type)
        return False


class TimeTracker:
    """
    Loguru-inspired time consumption tracker.

    Key features:
    - Global singleton-like usage via module-level `time_tracker`.
    - Context manager API: `with time_tracker("TASK")`.
    - Configurable sinks: console/file/callable, similar to `loguru.logger.add()`.
    - Summary output: task-wise total/avg/min/max/count.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}
        self._sinks: Dict[int, Sink] = {}
        self._sink_meta: Dict[int, Dict[str, Any]] = {}
        self._next_sink_id = 1

        # Behavior knobs
        self._emit_each: bool = False
        self._emit_each_level: str = "INFO"  # cosmetic
        self._time_unit: str = "ms"          # "s" or "ms"
        self._autoname_file_if_dir: bool = True
        self._include_timestamp: bool = True

        # Default sink: stdout (like a logger)
        self.add(sys.stdout)

    # ---------------------------
    # Public API (Loguru-ish)
    # ---------------------------

    def __call__(self, task: str) -> _TaskContext:
        """Return a context manager for the given task name."""
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task name must be a non-empty string")
        return _TaskContext(self, task.strip())

    def configure(
        self,
        *,
        emit_each: Optional[bool] = None,
        time_unit: Optional[str] = None,
        include_timestamp: Optional[bool] = None,
        autoname_file_if_dir: Optional[bool] = None,
    ) -> "TimeTracker":
        """
        Configure tracker behavior.

        - emit_each: if True, emit a log-like line after every `with` block.
        - time_unit: "ms" or "s"
        - include_timestamp: prefix output with timestamp
        - autoname_file_if_dir: if adding a sink with a directory path, auto-create a file inside it
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
            if autoname_file_if_dir is not None:
                self._autoname_file_if_dir = bool(autoname_file_if_dir)
        return self

    def add(self, target: SinkTarget, *, mode: str = "a", encoding: str = "utf-8") -> int:
        """
        Add a sink (like loguru.logger.add).

        target can be:
        - sys.stdout / sys.stderr (stream)
        - a file path (str/Path), or a directory path (see autoname_file_if_dir)
        - a callable(message: str) -> None
        - an open file-like object with .write()

        Returns a sink_id that can be passed to remove().
        """
        sink: Sink
        meta: Dict[str, Any] = {}

        if callable(target) and not hasattr(target, "write"):
            sink = target  # already a Sink callable
            meta["type"] = "callable"
            meta["target"] = repr(target)
        elif hasattr(target, "write"):
            sink = _StreamSink(target)  # type: ignore[arg-type]
            meta["type"] = "stream"
            meta["target"] = getattr(target, "name", repr(target))
        else:
            # str/Path -> file or directory
            p = Path(target)  # type: ignore[arg-type]
            if p.exists() and p.is_dir():
                if not self._autoname_file_if_dir:
                    raise ValueError(
                        f"'{p}' is a directory. Either pass a file path or set autoname_file_if_dir=True."
                    )
                filename = f"time_tracker_{datetime.now().strftime('%Y%m%d')}.log"
                p = p / filename
            elif str(p).endswith(os.sep) or (not p.suffix and self._autoname_file_if_dir):
                # Heuristic: treat as directory-ish
                p.mkdir(parents=True, exist_ok=True)
                filename = f"time_tracker_{datetime.now().strftime('%Y%m%d')}.log"
                p = p / filename

            file_sink = _FileSink(p, mode=mode, encoding=encoding)
            sink = file_sink
            meta["type"] = "file"
            meta["path"] = str(p)
            meta["closer"] = file_sink.close

        with self._lock:
            sink_id = self._next_sink_id
            self._next_sink_id += 1
            self._sinks[sink_id] = sink
            self._sink_meta[sink_id] = meta
        return sink_id

    def remove(self, sink_id: Optional[int] = None) -> None:
        """
        Remove a sink (like loguru.logger.remove).
        - If sink_id is None, remove all sinks.
        """
        with self._lock:
            if sink_id is None:
                ids = list(self._sinks.keys())
            else:
                ids = [sink_id]

            for sid in ids:
                sink = self._sinks.pop(sid, None)
                meta = self._sink_meta.pop(sid, None) or {}
                closer = meta.get("closer")
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass

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

        Returns the rendered summary string (also emitted to sinks).
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

        self._emit(rendered)

        if reset:
            self.clear()

        return rendered

    # ---------------------------
    # Internal: recording + emit
    # ---------------------------

    def _record(self, task: str, elapsed_s: float, exc_type: Optional[type] = None) -> None:
        with self._lock:
            self._records.setdefault(task, []).append(elapsed_s)

        if self._emit_each:
            msg = self._render_event(task, elapsed_s, exc_type=exc_type)
            self._emit(msg)

    def _emit(self, message: str) -> None:
        # Copy sinks to avoid holding the lock while writing
        with self._lock:
            sinks = list(self._sinks.values())

        # Ensure the message ends with newline (sink wrappers handle it too, but keep consistent)
        for sink in sinks:
            try:
                sink(message)
            except Exception:
                # don't let sink failures break the app
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

    def _render_event(self, task: str, elapsed_s: float, exc_type: Optional[type]) -> str:
        ts = self._ts_prefix()
        status = "OK" if exc_type is None else f"EXC:{getattr(exc_type, '__name__', str(exc_type))}"
        return f"{ts}{self._emit_each_level} | {status} | task={task} | elapsed={self._fmt_time(elapsed_s)}"

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

