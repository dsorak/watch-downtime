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
import logging.handlers
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import os
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path


def set_log_level(level_name) -> int:
    # Convert the level name to an actual logging level
    try:
        return getattr(logging, level_name.upper())
    except AttributeError:
        raise ValueError(f"Invalid log level: {level_name}")


def parse_time(value: str) -> int:
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


def seconds_to_hms(seconds:int) -> str:
    """Convert seconds to a human-readable format of hours, minutes, and seconds."""
    time = []
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        time.append(str(hours) + "h")
    if minutes > 0:
        time.append(str(minutes) + "m")
    if seconds > 0:
        time.append(str(seconds) + "s")
    return " ".join(time)


def ping_host(target_host:str) -> str | float:
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
            err_msg = str(result.stderr).strip() if result.stderr else "Unknown"
            return err_msg
        time_ms = float(result.stdout.split("time=")[1].split(" ms")[0])  # Extract the time
        return time_ms
    except Exception as e:
        return str(e)


def update(frame, times:deque, latencies:deque, warnings:deque, downtimes:deque, interval:int, threshold:int, target_host:str, *fargs):
    """Update the plot with new data and log to the logfile."""

    result = ping_host(target_host=target_host)

    times.append(datetime.datetime.now())
    if result is str: # TARGET_HOST ping failed
        latencies.append(0)  # Use 0 for downtime
        warnings.append(False)  # No warning when downtime
        downtimes.append(True)  # Downtimes are when latency is None
        logging.info(f"{target_host}: DOWN ({result})")
    elif result is float:
        latencies.append(result)
        if result > threshold:
            warnings.append(True)  # Warning for latency greater than threshold
            logging.warning(f"{target_host}: {result}ms")
        else:
            warnings.append(False)
            logging.debug(f"{target_host}: {result}ms")
        downtimes.append(False)

    # Convert to numpy arrays for easier manipulation
    times_np = np.array(times)
    latencies_np = np.array(latencies)

    # Update the line data
    line.set_data(times_np, latencies_np)
    ax.set_xlim(times_np[0], max(times_np[-1], times_np[0] + datetime.timedelta(seconds=interval)))

    # Dynamically adjust y-axis
    upper_limit = max(max(latencies_np) + 10, threshold)
    ax.set_ylim(0, upper_limit)

    # Highlight downtime and warning areas
    ax.fill_between(times_np, 0, upper_limit, where=np.array(downtimes), step='pre', color='red')
    ax.fill_between(times_np, 0, upper_limit, where=np.array(warnings), step='pre', color='orange')

    return line,


def parse_args() -> argparse.Namespace:

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
        "--log-console",
        action='store_true',
        help="Log output to the console (stderr)"
    )
    parser.add_argument(
        "--log-file",
        metavar="<file>",
        help="Logfile in which to log downtime",
        type=writable_file,
    )
    parser.add_argument(
        "--log-level",
        metavar="<level>",
        help="""Sets the logging level and must be one of: CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG, NOTSET
    If not specified, the environment variable "LOGLEVEL" will be used (if set).""",
        type=set_log_level,
        default=os.environ.get('LOGLEVEL', 'INFO')
    )
    return parser.parse_args()


def signal_handler(sig, frame):
    plt.close('all')  # Close the matplotlib window


if __name__ == '__main__':
    start_time = datetime.datetime.now()
    try:
        args = parse_args()
        kwargs = vars(args)

        log_handlers:list[logging.FileHandler | logging.StreamHandler] = []
        if args.log_console:
            # print("Adding console logging", file=sys.stderr)
            stream_handler = logging.StreamHandler(sys.stderr)
            stream_handler.setLevel(args.log_level)
            log_handlers.append(stream_handler)
        if args.log_file:
            # print(f"Adding file logging: {args.log_file}", file=sys.stderr)
            file_handler = logging.FileHandler(filename=args.log_file)
            file_handler.setLevel(args.log_level)
            log_handlers.append(file_handler)

        # print(f"Configuring logging: level={logging.getLevelName(args.log_level)}", file=sys.stderr)
        level_width = max(len(name) for name in logging._levelToName.values())
        logging.basicConfig(level=args.log_level,
                            handlers=log_handlers if log_handlers else None,
                            # format=f'%(asctime)s|%(name)s|%(levelname)-{level_width}s|%(message)s',
                            format=f'%(asctime)s|%(levelname)-{level_width}s|%(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S%z'
        )

        if args.window < args.interval:
            args.window = args.interval * 2
            logging.warning(f"Window cannot be smaller than 2x <interval>, setting window to: {seconds_to_hms(args.window)}")
        window_points = args.window // args.interval # The number of "window" points to display
        max_points = (60 // 15) * 60 * 24  # Set a reasonable limit to the number of points that the chart can display (15s interval, over 24h)

        if window_points > max_points:  # If the plot has too many points, it will be identified as unresponsive by the system
            logging.warning(f"Plotting window is too large: {window_points} points (reducing to {max_points} points)")
            window_points = max_points

        fig, ax = plt.subplots()
        fig.patch.set_facecolor('#303030' if args.dark else 'white')  # Set the figure background color
        ax.set_facecolor('#505050' if args.dark else 'white')  # Set the axes background color

        line, = ax.plot([], [], lw=2)
        ax.set_ylim(0, args.threshold)  # Initial y-axis limit, will adjust dynamically
        ax.set_xlim(0, window_points * args.interval)
        ax.set_xlabel('Time', color='white' if args.dark else 'black')
        ax.set_ylabel('Ping Latency (ms)', color='white' if args.dark else 'black')
        ax.tick_params(axis='x', colors='white' if args.dark else 'black')
        ax.tick_params(axis='y', colors='white' if args.dark else 'black')

        plt.xticks(rotation=90)  # Rotate x-axis labels to 90 degrees
        plt.subplots_adjust(left=0.1, right=0.99, top=0.99, bottom=0.2)  # Adjust the bottom to prevent label cutoff

        # Deques to store the time and latency data
        times = deque(maxlen=window_points)
        latencies = deque(maxlen=window_points)
        warnings = deque(maxlen=window_points)
        downtimes = deque(maxlen=window_points)

        # Create animation
        ani = animation.FuncAnimation(fig,
                                      func=update,
                                      interval=args.interval * 1000,
                                      fargs=(times, latencies, warnings, downtimes, args.interval, args.threshold, args.host),
                                      cache_frame_data=False
        )
        try:
            plt.get_current_fig_manager().set_window_title('Network Downtime Monitor') # type: ignore
        except Exception as e:
            logging.exception(msg="Unable to set window title")

        logging.info(f"Monitoring started: {__file__}: {kwargs}")

        # Register the signal handler
        signal.signal(signal.SIGINT, signal_handler)
        plt.show()

    except Exception as e:
        logging.exception(msg="Unexpected exception")
        
    finally:
        elapsed = seconds_to_hms(int((datetime.datetime.now()-start_time).total_seconds()))
        logging.info(f"Monitoring stopped: Watched for {elapsed}")
