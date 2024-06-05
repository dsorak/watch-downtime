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
import matplotlib.animation as ani
import matplotlib.figure as fig
import matplotlib.pyplot as plt
import matplotlib.axes as axes
import numpy as np
import os
import psutil
import signal
import subprocess
import sys
from collections import deque
from pathlib import Path
from time import sleep
from typing import NamedTuple, List, Any


def set_log_level(level_name: str) -> int:
    """Convert the level name to an actual logging level"""
    try:
        return getattr(logging, level_name.upper())
    except AttributeError:
        raise ValueError(f"Invalid log level: {level_name}")


def parse_time(value: str) -> int:
    """Parses a time string with a suffix to convert it to seconds.
    If no suffix exists, assume seconds.
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
        units = {  # Conversion factors
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


def writable_file(filepath: str) -> Path:
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
        return path.absolute()
    except PermissionError as e:
        raise argparse.ArgumentTypeError(f"Insufficient permissions: {path.absolute()} ({str(e)})")
    except IOError as e:
        raise argparse.ArgumentTypeError(f"Unable to access: {path.absolute()} ({str(e)})")


def seconds_to_hms(seconds: int) -> str:
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
    """Parse command line arguments"""
    class UltimateHelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
        pass

    parser = argparse.ArgumentParser(
        description="Monitor your internet connection for downtime or unacceptable latency. You must choose a logging option, one of --logfile, --console, or --plot.",
        formatter_class=UltimateHelpFormatter
    )
    required_actions: List[argparse.Action] = []
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
        help="The 'warning' latency threshold for logging (in ms). If this threshold is exceeded, a WARNING log entry will be made.",
        type=float,
        default=100.0
    )
    required_actions.append(
        parser.add_argument(
            "--logfile",
            metavar="<file>",
            help="Logfile in which to log downtime. If not set, logs will not be saved",
            type=writable_file
        )
    )
    required_actions.append(
        parser.add_argument(
            "--console",
            action='store_true',
            help="Log output to the console (stdout)"
        )
    )
    required_actions.append(
        parser.add_argument(
            "--plot",
            metavar="<window>",
            nargs="?",
            help="""An optional graph window in seconds, or use a suffix (E.g. '2d'):
            's': Seconds
            'm': Minutes
            'h': Hours
            'd': Days
            'w': Weeks
If not set, a plot window will not be created.""",
            type=parse_time,
            const='5h'
        )
    )
    parser.add_argument(
        "--dark",
        action='store_true',
        help='Enable dark mode for plotting'
    )
    required_actions.append(
        parser.add_argument(
            "--stop",
            action='store_true',
            help='Stop any running monitoring processes (exits immediately unless another monitoring task is specified)'
        )
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

    if not any(getattr(result, action.dest, None) for action in required_actions):
        parser.error(f"You must specify at least one of: --{', --'.join(action.dest for action in required_actions)}")

    return result


class Pinger:
    """Base class for pinging a remote host, capturing latency, and logging
    downtime, warnings, or all results (based upon the logging level)
    """

    def __init__(self, target_host: str, threshold: float):
        self.target_host = target_host
        self.threshold = threshold

    def ping_host(self) -> float:
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
                ["ping", "-c", "1", self.target_host],
                text=True,  # Equivalent to universal_newlines=True in Python 3.7+
                capture_output=True  # Captures both stdout and stderr
            )
            if result.returncode != 0:
                msg = result.stderr.strip()
                if not msg:
                    lines: List[str] = result.stdout.strip().split("\n")
                    msg = lines[-1]
                if not msg:
                    msg = "Timed out"
                logger.error(f"Host: {self.target_host}: DOWN ({msg})")
                return 0
            result = float(result.stdout.split("time=")[1].split(" ms")[0])  # Extract the time (ms)
            if result > self.threshold:
                logger.warning(f"Host: {self.target_host}: {result}ms")
            else:
                logger.debug(f"Host: {self.target_host}: {result}ms")
            return result
        except Exception as e:
            logger.error(f"Host: {self.target_host}: DOWN ({str(e)})")
            return 0


class Plotter(Pinger):
    """Class for plotting the latency and downtime of the network"""

    MAX_POINTS = 1800
    THRESHOLD_PLOT_BUFFER = 10  # ms

    def __init__(self, target_host: str, threshold: float, interval: int, window: int, dark_mode: bool):
        super().__init__(target_host=target_host, threshold=threshold)

        self.interval = interval
        self.window = window
        self.interrupted = False

        if self.window < interval:
            self.window = interval * 2
            logger.warning(f"Window cannot be smaller than 2x <interval>, setting window to: {seconds_to_hms(self.window)}")

        window_points = self.window // interval

        if window_points > self.MAX_POINTS:
            window_points = self.MAX_POINTS
            self.window = window_points * interval
            logger.warning(f"Plotting window is too large, reducing to: {window_points} points or {seconds_to_hms(self.window)} at {seconds_to_hms(self.interval)} intervals (was {seconds_to_hms(window)})")

        # Deques to store the time and latency data
        self.times = deque(maxlen=window_points)
        self.latencies = deque(maxlen=window_points)
        self.warnings = deque(maxlen=window_points)
        self.downtimes = deque(maxlen=window_points)
        self.max_latency = self.threshold

        self.fig: fig.Figure
        self.ax: axes.Axes
        self.fig, self.ax = plt.subplots()

        self.fig.patch.set_facecolor('#303030' if dark_mode else 'white')
        self.ax.set_facecolor('#505050' if dark_mode else 'white')

        self.line, = self.ax.plot([], [], lw=2)
        self.ax.set_ylim(0, self.threshold + self.THRESHOLD_PLOT_BUFFER)
        self.ax.set_xlabel('Time', color='white' if dark_mode else 'black')
        self.ax.set_ylabel('Ping Latency (ms)', color='white' if dark_mode else 'black')
        self.ax.tick_params(axis='x', colors='white' if dark_mode else 'black')
        self.ax.tick_params(axis='y', colors='white' if dark_mode else 'black')

        plt.xticks(rotation=90)
        plt.subplots_adjust(left=0.1, right=0.99, top=0.99, bottom=0.2)

        try:
            plt.get_current_fig_manager().set_window_title('Network Downtime Monitor')
        except Exception as e:
            logger.exception("Unable to set window title")

    def update_plot(self, frame: Any):
        """Update the plot with new data"""
        self.times.append(datetime.datetime.now())
        result = self.ping_host()
        self.latencies.append(result)

        if result + self.THRESHOLD_PLOT_BUFFER > self.max_latency:
            self.max_latency = result + self.THRESHOLD_PLOT_BUFFER  # Leave a little space above the line
            self.ax.set_ylim(0, self.max_latency)

        if result == 0:
            self.downtimes.append(True)  # Downtimes are when latency is 0
        else:
            self.downtimes.append(False)

        if result > self.threshold:
            self.warnings.append(True)  # Warnings are when latency is greater than threshold
        else:
            self.warnings.append(False)

        if len(self.latencies) > 1:  # Don't plot unless we have at least 2 points
            self.line.set_data(self.times, self.latencies)
            self.ax.set_xlim(self.times[0], self.times[-1])
            self.ax.fill_between(self.times, 0, self.max_latency, where=self.downtimes, step='pre', color='red')
            self.ax.fill_between(self.times, 0, self.max_latency, where=self.warnings, step='pre', color='orange')

        return self.line,

    def start_monitoring(self) -> bool:
        """Start monitoring the network"""
        logger.info(f"Plotting:   STARTED|Window: {seconds_to_hms(self.window)} at {seconds_to_hms(self.interval)} intervals ({self.window // self.interval} points)")
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        _ = ani.FuncAnimation(self.fig, self.update_plot, interval=self.interval * 1000, blit=True, cache_frame_data=False)
        plt.show()
        elapsed = seconds_to_hms(int((datetime.datetime.now()-start_time).total_seconds()))
        logger.info(f"Plotting:   STOPPED|Plotted for: {elapsed}")
        return self.interrupted

    def signal_handler(self, sig, frame):
        plt.close('all')
        self.interrupted = True
        # Restore the default signal handlers
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


class Watcher(Pinger):
    """Class for watching the network without plotting"""

    def __init__(self, target_host: str, threshold: float, interval: int):
        super().__init__(target_host=target_host, threshold=threshold)
        self.interval = interval

    def start_monitoring(self) -> bool:
        """Start monitoring the network"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        try:
            while True:
                self.ping_host()
                sleep(self.interval)
        except self.SignalInterrupt:
            return True

    class SignalInterrupt(Exception):
        """Custom exception for signal interrupts"""
        pass

    def signal_handler(self, sig, frame):
        # Restore the default signal handlers
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        raise self.SignalInterrupt  # Raise the custom exception to break out of the monitoring loop


def check_running(stop: bool) -> List[psutil.Process]:
    """Check if running instances of this app exist, optionally attempting
    to stop them, returning any remaining running processes

    Args:
        stop (bool): If True, attempt to stop the running processes

    Returns:
        List[psutil.Process]: List of any remaining running processes
    """
    current_pid = os.getpid()
    running_instances: List[psutil.Process] = []
    for proc in psutil.process_iter(['name', 'cmdline', 'username']):
        try:
            if proc.pid != current_pid and proc.info['name'].startswith('python') and script_name in " ".join(proc.info['cmdline']):
                if stop:
                    sys.stderr.write(f"Stopping: {proc.pid}")
                    proc.terminate()
                    sys.stderr.write(f" (STOPPED)\n")
                    sleep(1)  # Give the process a chance to log the stop
                else:
                    running_instances.append(proc)
        except (psutil.NoSuchProcess, psutil.ZombieProcess) as e:
            sys.stderr.write(f" (IGNORED: {e.__class__.__name__})\n")
        except Exception as e:  # psutil.AccessDenied:
            sys.stderr.write(f" (FAILED: {e.__class__.__name__}: {proc.info['username']})\n")
            running_instances.append(proc)
    return running_instances


def configure_logger(level: int, console: bool, logfile: Path) -> logging.Logger:
    """Configure the logger"""
    logger = logging.getLogger(os.path.basename(sys.argv[0]))
    level_width = max(len(name) for name in logging._levelToName.values())
    formatter = logging.Formatter(fmt=f'%(asctime)s|%(process)+7s|%(levelname)-{level_width}s|%(message)s', datefmt='%Y-%m-%d %H:%M:%S%z')
    logger.setLevel(level)
    if console:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if logfile:
        handler = logging.FileHandler(filename=logfile)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


if __name__ == '__main__':
    start_time = datetime.datetime.now()
    script_name = os.path.basename(sys.argv[0])
    args = parse_args()
    logger = configure_logger(args.level, args.console, args.logfile)

    try:
        running_instances = check_running(args.stop)
        if running_instances:
            sys.stderr.write(f"At least one other instance of {script_name} is still running: {', '.join(str(proc.pid) for proc in running_instances)}")
            if not args.stop:
                sys.stderr.write(" (try using --stop)")
            sys.stderr.write("\n")
            sys.exit(1)

        logger.info(f"Monitoring: STARTED|CMD: {__file__}|ARGS: {vars(args)}|LEVEL: {logging._levelToName[args.level]}")

        interrupted = False
        if args.plot:
            plotter = Plotter(target_host=args.host, threshold=args.threshold, interval=args.interval, window=args.plot, dark_mode=args.dark)
            interrupted = plotter.start_monitoring()

        # If the plotter exits without being interrupted (not do due to SIGINT or SIGTERM)
        # AND console logging or file logging is enabled, continue monitoring
        if not interrupted and (args.console or args.logfile):
            watcher = Watcher(target_host=args.host, threshold=args.threshold, interval=args.interval)
            watcher.start_monitoring()

    except Exception as e:
        logger.exception(f"Unexpected exception: {e}")

    elapsed = seconds_to_hms(int((datetime.datetime.now()-start_time).total_seconds()))
    logger.info(f"Monitoring: STOPPED|Monitored for: {elapsed}")
