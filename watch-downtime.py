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
import psutil
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path
from time import sleep
from typing import NamedTuple


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
        default='10s'
    )
    parser.add_argument(
        "--threshold",
        metavar="<ms>",
        help="The 'warning' latency threshold for logging (in ms). If this threshold is exceeded, a log entry will be made.",
        type=int,
        default=100
    )
    fileArg = parser.add_argument(
        "--logfile",
        metavar="<file>",
        help="Logfile in which to log downtime. If not set, logs will not be saved",
        type=writable_file,
    )
    consoleArg = parser.add_argument(
        "--console",
        action='store_true',
        help="Log output to the console (stderr)"
    )
    plotArg = parser.add_argument(
        "--plot",
        metavar="<window>",
        nargs="?",
        help="""An optional graph window in seconds, or use a suffix (E.g. '2d'):
        's': Seconds
        'm': Minutes
        'h': Hours
        'd': Days
        'w': Weeks
        If not set, a plot window will not be created.
    """,
        type=parse_time,
        const='12h'
    )
    parser.add_argument(
        "--dark",
        action='store_true',
        help='Enable dark mode'
    )
    parser.add_argument(
        "--level",
        metavar="<log_level>",
        help="""Sets the logging level and must be one of: CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG, NOTSET
    If not specified, the environment variable "LOGLEVEL" will be used (if set).""",
        type=set_log_level,
        default=os.environ.get('LOGLEVEL', 'INFO')
    )
    
    result = parser.parse_args()
    
    if not (result.console or result.logfile or result.plot):
        parser.error(f"You must specify at least one of: --{fileArg.dest}, --{consoleArg.dest}, or --{plotArg.dest}")

    return result


def ping_host(target_host:str, threshold:float) -> float:
    """Ping the host and return the latency, logging messages at the same time.

    Args:
        target_host (str): The hostname/IP address to check
        threshold (float): The threshold latency (ms) at which to report a warning

    Returns:
        float: The milliseconds of latency from the ping
                >0 == Success
                 0 == Failed
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "1", target_host],
            text=True,  # Equivalent to universal_newlines=True in Python 3.7+
            capture_output=True  # Captures both stdout and stderr
        )
        if result.returncode != 0:
            if result.stderr:
                msg = result.stderr.strip()
            elif result.stdout:
                lines:list[str] = result.stdout.split("\n")
                msg = lines[-1]
            else:
                msg = "Unknown Error"
            logger.error(f"Host: {target_host}: DOWN ({msg})")
            return 0
        result = float(result.stdout.split("time=")[1].split(" ms")[0])  # Extract the time (ms)
        if result > threshold:
            logger.warning(f"Host: {target_host}: {result}ms")
        else:
            logger.debug(f"Host: {target_host}: {result}ms")
        return result
    except Exception as e:
        logger.error(f"Host: {target_host}: DOWN ({str(e)})")
        return 0


def plot_update(frame, line, times:deque, latencies:deque, warnings:deque, downtimes:deque, interval:int, threshold:int, target_host:str, *fargs):
    """Update the plot with new data and log to the logfile."""

    result = ping_host(target_host=target_host, threshold=threshold)

    times.append(datetime.datetime.now())
    latencies.append(result)
    
    if result == 0:
        downtimes.append(True)  # Downtimes are when latency is 0
    else:
        downtimes.append(False)
        
    if result > threshold:
        warnings.append(True)  # Warning for latency greater than threshold
    else:
        warnings.append(False)

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


class SignalInterrupt(Exception):
    pass


def signal_handler_plot(sig, frame):
    plt.close('all')  # Close the matplotlib window
    global log_loop
    log_loop = False


def signal_handler_log(sig, frame):
    raise SignalInterrupt  # Raise the custom exception


def log_updates(interval, threshold, target_host):
    while log_loop:
        ping_host(target_host=target_host, threshold=threshold)
        sleep(interval)


def check_if_running():  # TODO: This does not work
    current_pid = os.getpid()
    script_name = os.path.basename(sys.argv[0])
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        if proc.info['pid'] == current_pid:
            continue
        if script_name in proc.info['cmdline']:
            return True
    return False


logger = logging.getLogger(__name__)
if __name__ == '__main__':
    if check_if_running():
        print(f"Another instance of {sys.argv[0]} is already running.")
        sys.exit(1)

    start_time = datetime.datetime.now()
    try:
        args = parse_args()
        kwargs = vars(args)

        level_width = max(len(name) for name in logging._levelToName.values())
        formatter = logging.Formatter(fmt=f'%(asctime)s|%(levelname)-{level_width}s|%(message)s', datefmt='%Y-%m-%d %H:%M:%S%z')
        logger.setLevel(args.level)
        if args.console:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        if args.logfile:
            handler = logging.FileHandler(filename=args.logfile)
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        logger.info(f"Monitoring started: {__file__}: {kwargs} ({logging._levelToName[args.level]})")

        log_loop = args.console or args.logfile  # Set this before the signal_handler_plot() is installed
        if args.plot:
            if args.plot < args.interval:
                args.plot = args.interval * 2
                logger.warning(f"Window cannot be smaller than 2x <interval>, setting window to: {seconds_to_hms(args.plot)}")

            window_points = args.plot // args.interval
            max_points = 2048

            if window_points > max_points:
                logger.warning(f"Plotting window is too large: {window_points} points (reducing to {max_points} points)")
                window_points = max_points

            # Deques to store the time and latency data
            times = deque(maxlen=window_points)
            latencies = deque(maxlen=window_points)
            warnings = deque(maxlen=window_points)
            downtimes = deque(maxlen=window_points)

            fig, ax = plt.subplots()
            
            fig.patch.set_facecolor('#303030' if args.dark else 'white')
            ax.set_facecolor('#505050' if args.dark else 'white')

            line, = ax.plot([], [], lw=2)
            ax.set_ylim(0, args.threshold)
            ax.set_xlim(0, window_points * args.interval)
            ax.set_xlabel('Time', color='white' if args.dark else 'black')
            ax.set_ylabel('Ping Latency (ms)', color='white' if args.dark else 'black')
            ax.tick_params(axis='x', colors='white' if args.dark else 'black')
            ax.tick_params(axis='y', colors='white' if args.dark else 'black')

            plt.xticks(rotation=90)
            plt.subplots_adjust(left=0.1, right=0.99, top=0.99, bottom=0.2)

            ani = animation.FuncAnimation(fig,
                                          func=plot_update,
                                          interval=args.interval * 1000,
                                          fargs=(line, times, latencies, warnings, downtimes, args.interval, args.threshold, args.host),
                                          cache_frame_data=False
            )
            try:
                plt.get_current_fig_manager().set_window_title('Network Downtime Monitor')
            except Exception as e:
                logger.exception(msg="Unable to set window title")

            signal.signal(signal.SIGINT, signal_handler_plot)  # Register the signal handler which will shut down the plot
            signal.signal(signal.SIGTERM, signal_handler_plot)  # Register the signal handler which will shut down the plot
            plt.show()

        # If the plot exits (not do due to SIGINT or SIGTERM) and console or file logging is enabled, continue monitoring
        if log_loop:
            signal.signal(signal.SIGINT, signal_handler_log)  # Register the signal handler which will shut down the logging
            signal.signal(signal.SIGTERM, signal_handler_log)  # Register the signal handler which will shut down the logging
            log_updates(args.interval, args.threshold, args.host)

    except SignalInterrupt:
        pass
    
    except Exception as e:
        logger.exception(msg="Unexpected exception")

    finally:
        elapsed = seconds_to_hms(int((datetime.datetime.now()-start_time).total_seconds()))
        logger.info(f"Monitoring stopped: Watched for {elapsed}")
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # Restore the default signal handler for SIGINT
        signal.signal(signal.SIGTERM, signal.SIG_DFL)  # Restore the default signal handler for SIGTERM
