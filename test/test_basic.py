# example_main.py
import sys
import time
from time_consumption_tracker import time_tracker
from another_file import do_something

def main():
    # Configure like loguru: choose sinks + behavior
    time_tracker.remove()                 # remove default stdout
    time_tracker.add(sys.stdout)          # console
    time_tracker.add("logs/")             # directory -> logs/time_tracker_YYYYMMDD.log
    time_tracker.configure(emit_each=True, time_unit="ms")

    with time_tracker("startup"):
        time.sleep(0.05)

    with time_tracker("load_data"):
        time.sleep(0.12)

    with time_tracker("load_data"):
        time.sleep(0.08)

    with time_tracker("train"):
        time.sleep(0.2)
    
    for i in range(5):
        do_something()

    time_tracker.summary(sort_by="total")

if __name__ == "__main__":
    main()

