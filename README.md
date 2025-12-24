# Python package for time consumption tracker

## Usage

```bash

from time_consumption_tracker import time_tracker

time_tracker.add(sys.stdout)             # console sink
time_tracker.add("logs/timing.log")      # file sink (path or directory)
time_tracker.configure(emit_each=True)   # emit a line for each completed task

with time_tracker("LOAD_DATA"):
    ...

time_tracker.summary()                   # prints summary to configured sinks

```
