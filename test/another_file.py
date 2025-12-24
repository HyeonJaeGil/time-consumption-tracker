import time
from time_consumption_tracker import time_tracker


def do_something():
    with time_tracker("in_another_file"):
        time.sleep(0.15)


def do_something_second():
    with time_tracker("in_another_file_second"):
        time.sleep(0.19)
