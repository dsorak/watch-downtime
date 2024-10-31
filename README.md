# watch-downtime

Simple Python script to monitor network up-time and latency and to plot the results.

## Usage

```text
usage: watch-downtime.py [-h] [--host <host/ip>] [--interval <span>] [--threshold <ms>] [--logfile <file>] [--console] [--plot [<window>]] [--dark] [--stop] [--level <log_level>]

Monitor your internet connection for downtime or unacceptable latency. You must choose a logging option, one of --logfile, --console, or --plot.

options:
  -h, --help           show this help message and exit
  --host <host/ip>     Hostname to ping for downtime testing (default: google.com)
  --interval <span>    The ping interval in seconds, or use a suffix (E.g. '1m'):
                               's': Seconds
                               'm': Minutes
                               'h': Hours
                               'd': Days
                               'w': Weeks
                            (default: 10s)
  --threshold <ms>     The 'warning' latency threshold for logging (in ms). If this threshold is exceeded, a WARNING log entry will be made. (default: 100.0)
  --logfile <file>     Logfile in which to log downtime. If not set, logs will not be saved (default: None)
  --console            Log output to the console (stdout) (default: False)
  --plot [<window>]    An optional graph window in seconds, or use a suffix (E.g. '2d'):
                                   's': Seconds
                                   'm': Minutes
                                   'h': Hours
                                   'd': Days
                                   'w': Weeks
                       If not set, a plot window will not be created. (default: None)
  --dark               Enable dark mode for plotting (default: False)
  --stop               Stop any running monitoring processes (exits immediately unless another monitoring task is specified) (default: False)
  --level <log_level>  Sets the logging level and must be one of: CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG, NOTSET
                           If not specified, the environment variable "LOGLEVEL" will be used (if set). (default: INFO)

```
