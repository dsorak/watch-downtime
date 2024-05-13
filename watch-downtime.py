#!/usr/bin/env python3
# coding: utf-8

# Author: Daniel Sorak
# Copyright: 2024 Daniel Sorak
# License: GPL (General Public License)

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import argparse
import datetime
import logging
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import os
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path


def signal_handler(sig, frame):
    plt.close('all')  # Close the matplotlib window


def set_log_level(level_name):
    # Convert the level name to an actual logging level
    try:
        return getattr(logging, level_name.upper())
    except AttributeError:
        raise ValueError(f"Invalid log level: {level_name}")


def parse_time(value:str):
    """Parses a time string with a suffix to convert it to seconds.
    Supported suffixes: s for seconds, m for minutes, h for hours, d for days.

    Args:
        value (str): The value to parse

    Raises:
        ValueError: Raised if the value is invalid

    Returns:
        int: The number of seconds represented by the given value
    """
    if value[-1].isdigit():  # Check if there's no suffix and assume seconds
        return int(value)
    else:
        units = { # Conversion factors
            's': 1,
            'm': 60,
            'h': 60 * 60,
            'd': 60 * 60 * 24,
            'w': 60 * 60 * 24 * 7}
        number = int(value[:-1])  # The numeric part
        unit = value[-1]  # The suffix
        if unit in units:
            return number * units[unit]
        else:
            raise ValueError(f"Invalid time unit '{unit}' in '{value}'. Use 's', 'm', 'h', 'd', or 'w'.")


def writable_file(filepath) -> Path:
    """Check if the given path refers to a writeable file, or if it does not exist, try to create it as writeable.

    Args:
        path (str): The path to the intended file, either relative or absolute

    Raises:
        argparse.ArgumentTypeError: If the path is invalid (message contains reason)

    Returns:
        str: The string containing the absolute path
    """
    path = Path(filepath)
    try:
        if path.exists():  # If the file exists, try to open it in append mode to check write-ability
            if not path.is_file():
                raise argparse.ArgumentTypeError(f"Path is not a file: {path.absolute()}")
            with path.open('a'):
                pass
        else:  # If the file does not exist, try creating it (also checks directory write-ability indirectly)
            path.touch()
            # path.unlink()  # Clean up immediately after creating
        return path.absolute()
    except PermissionError as e:
        raise argparse.ArgumentTypeError(f"Insufficient permissions: {path.absolute()} ({str(e)})")
    except IOError as e:
        raise argparse.ArgumentTypeError(f"Unable to access: {path.absolute()} ({str(e)})")


def seconds_to_hms(seconds:int):
    """Convert seconds to a human-readable format of hours, minutes, and seconds."""
    time = []
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if (hours > 0):
        time.append(str(hours) + "h")
    if (minutes > 0):
        time.append(str(minutes) + "m")
    if (seconds > 0):
        time.append(str(seconds) + "s")
    return " ".join(time)


def ping_host(target_host:str):
    """Ping the host and return the latency.

    Args:
        target_host (str): The hostname/IP address to check

    Returns:
        float, None: The milliseconds of latency from the ping
        None, str: None to indicate error/failure and a string error message
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "1", target_host],
            text=True,  # Equivalent to universal_newlines=True in Python 3.7+
            capture_output=True  # Captures both stdout and stderr
        )
        if result.returncode != 0:
            err_msg = f" ({str(result.stderr).strip()})" if result.stderr else "Unknown"
            # with open(logfile, "a") as f: # Log downtime
            #     f.write(f"{datetime.datetime.now()} - {target_host}: DOWN{err_msg}\n")
            return None, err_msg
        time_ms = float(result.stdout.split("time=")[1].split(" ms")[0])  # Extract the time
        return time_ms, None
    except Exception as e:
        # with open(logfile, "a") as f: # Log downtime
        #     f.write(f"{datetime.datetime.now()} - {target_host}: EXCEPTION ({str(e)})\n")
        return None, str(e)


def update(frame, *fargs):
    """Update the plot with new data and log to the logfile."""
    now = datetime.datetime.now() #.timestamp()  # Current timestamp
    latency, err_msg = ping_host(target_host=TARGET_HOST)

    TIMES.append(now)
    if latency is None: # TARGET_HOST ping failed
        LATENCIES.append(0)  # Use 0 for downtime
        WARNINGS.append(False)  # No warning when downtime
        DOWNTIMES.append(True)  # Downtimes are when latency is None
        with open(LOG_FILE, "a") as f: # Log downtime
            f.write(f"{datetime.datetime.now()} - {TARGET_HOST}: DOWN ({err_msg})\n")
    else:
        LATENCIES.append(latency)
        if latency > LATENCY_THRESHOLD:
            WARNINGS.append(True)  # Warning for latency greater than threshold
            with open(LOG_FILE, "a") as f:
                f.write(f"{now} - {TARGET_HOST}: {latency}ms\n")
        else:
            WARNINGS.append(False)
        DOWNTIMES.append(False)

    # Convert to numpy arrays for easier manipulation
    times_np = np.array(TIMES)
    latencies_np = np.array(LATENCIES)

    # Update the line data
    line.set_data(times_np, latencies_np)
    ax.set_xlim(times_np[0], max(times_np[-1], times_np[0] + datetime.timedelta(seconds=SAMPLING_INTERVAL)))

    # Dynamically adjust y-axis
    upper_limit = max(max(latencies_np) + 10, LATENCY_THRESHOLD)
    ax.set_ylim(0, upper_limit)

    # Highlight downtime and warning areas
    ax.fill_between(times_np, 0, upper_limit, where=np.array(DOWNTIMES), step='pre', color='red')
    ax.fill_between(times_np, 0, upper_limit, where=np.array(WARNINGS), step='pre', color='orange')

    return line,


class UltimateHelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


parser = argparse.ArgumentParser(
    description="Monitor internet connection for downtime or unacceptable latency",
    formatter_class=UltimateHelpFormatter
)
parser.add_argument(
    "--host",
    metavar="<host/ip>",
    help="Hostname to ping for downtime testing",
    default="google.com"
)
parser.add_argument(
    "--logfile",
    metavar="<file>",
    help="Logfile in which to log downtime",
    type=writable_file,
    default="./downtime_log.txt"
)
parser.add_argument(
    "--interval",
    metavar="<span>",
    help="""The ping interval in seconds, or use a suffix (E.g. '1m'):
    's': Seconds
    'm': Minutes
    'h': Hours
    'd': Days
    'w': Weeks
""",
    type=parse_time,
    default='15s'
)
parser.add_argument(
    "--threshold",
    metavar="<ms>",
    help="The 'warning' latency threshold for logging (in ms). If this threshold is exceeded, a log entry will be made.",
    type=int,
    default=100
)
parser.add_argument(
    "--window",
    metavar="<span>",
    help="""The graph window in seconds, or use a suffix (E.g. '2d'):
    's': Seconds
    'm': Minutes
    'h': Hours
    'd': Days
    'w': Weeks
""",
    type=parse_time,
    default='24h'
)
parser.add_argument(
    "--dark",
    action='store_true',
    help='Enable dark mode'
)
parser.add_argument(
    "--log-level",
    metavar="<level>",
    help="""Sets the logging level and must be one of: CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG, NOTSET
If not specified, the environment variable "LOGLEVEL" will be used (if set).""",
    type=set_log_level,
    default=os.environ.get('LOGLEVEL', 'ERROR')
)
try:
    args = parser.parse_args()
except argparse.ArgumentError as e:
    parser.error(str(e))

# Constants
TARGET_HOST = args.host
LOG_FILE = args.logfile
SAMPLING_INTERVAL = int(args.interval) # seconds
if args.window < SAMPLING_INTERVAL:
    args.window = SAMPLING_INTERVAL * 2
    print(f"Window cannot be smaller than 2x <interval>, setting window to: {seconds_to_hms(args.window)}", file=sys.stderr)
WINDOW_POINTS = args.window // SAMPLING_INTERVAL # The number of "window" points to display
LATENCY_THRESHOLD = args.threshold
MAX_POINTS = (60 / 15) * 60 * 24  # Set a reasonable limit to the number of points that the chart can display (15s interval, over 24h)
START_TIME = datetime.datetime.now()

# Deques to store the time and latency data
TIMES = deque(maxlen=WINDOW_POINTS)
LATENCIES = deque(maxlen=WINDOW_POINTS)
WARNINGS = deque(maxlen=WINDOW_POINTS)
DOWNTIMES = deque(maxlen=WINDOW_POINTS)

try:
    logging.basicConfig(level=args.log_level)

    if WINDOW_POINTS > MAX_POINTS:  # If the plot has too many points, it will be identified as unresponsive by the system
        print(f"Please reduce the window ({seconds_to_hms(args.window)}) or increase the interval ({SAMPLING_INTERVAL}s) to display less than {MAX_POINTS} points. Current settings yield: {WINDOW_POINTS} points", file=sys.stderr)
        sys.exit(0)

    print(f"Starting network downtime watch:")
    print(f"    Ping Host:       {TARGET_HOST}")
    print(f"    Logfile:         {LOG_FILE}")
    print(f"    Sample Interval: {SAMPLING_INTERVAL}s")
    print(f"    Latency Warning: {LATENCY_THRESHOLD}ms")
    print(f"    Plot Window:     {seconds_to_hms(args.window)}")
    print(f"    Plot Points:     {WINDOW_POINTS}")

    # Initialize plot
    fig, ax = plt.subplots()
    fig.patch.set_facecolor('#303030' if args.dark else 'white')  # Set the figure background color
    ax.set_facecolor('#505050' if args.dark else 'white')  # Set the axes background color

    line, = ax.plot([], [], lw=2)
    ax.set_ylim(0, LATENCY_THRESHOLD)  # Initial y-axis limit, will adjust dynamically
    ax.set_xlim(0, WINDOW_POINTS * SAMPLING_INTERVAL)
    ax.set_xlabel('Time', color='white' if args.dark else 'black')
    ax.set_ylabel('Ping Latency (ms)', color='white' if args.dark else 'black')
    ax.tick_params(axis='x', colors='white' if args.dark else 'black')
    ax.tick_params(axis='y', colors='white' if args.dark else 'black')

    plt.xticks(rotation=90)  # Rotate x-axis labels to 90 degrees
    plt.subplots_adjust(left=0.1, right=0.99, top=0.99, bottom=0.2)  # Adjust the bottom to prevent label cutoff

    # Create animation
    ani = animation.FuncAnimation(fig, update, interval=SAMPLING_INTERVAL * 1000, cache_frame_data=False)

    try:
        plt.get_current_fig_manager().set_window_title('Network Downtime Monitor') # type: ignore
    except Exception as e:
        print("Unable to set window title: " + str(e), file=sys.stderr)

    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.datetime.now()} - Monitoring started\n")

    # Register the signal handler
    signal.signal(signal.SIGINT, signal_handler)
    plt.show()

except Exception as e:
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.datetime.now()} - Unexpected exception: {str(e)}\n")

elapsed = seconds_to_hms(int((datetime.datetime.now()-START_TIME).total_seconds()))
print(f"\nStopping network downtime watch after {elapsed}")
with open(LOG_FILE, "a") as f:
    f.write(f"{datetime.datetime.now()} - Monitoring stopped (Elapsed: {elapsed})\n")
