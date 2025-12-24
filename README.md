# Python package for time consumption tracker

## Usage

```bash

from loguru import logger
from time_consumption_tracker import time_tracker

# Optionally bind a specific loguru Logger instance
time_tracker.use_logger(logger)
time_tracker.configure(emit_each=True)   # emit a line for each completed task

with time_tracker("LOAD_DATA", level="DEBUG"):
    ...  # work to be measured

time_tracker.summary()                   # prints summary through loguru

```
