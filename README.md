# watch-downtime

Simple Python script to monitor network up-time and latency and to plot the results.

## Usage

```text
watch-downtime.py [-h] [--host <host/ip>] [--logfile <file>] [--interval <span>] [--threshold <ms>] [--window <span>] [--dark] [--log-level <level>]

Monitor internet connection for downtime or unacceptable latency

options:
  -h, --help           Show this help message and exit
  --host <host/ip>     Hostname to ping for downtime testing (default: google.com)
  --logfile <file>     Logfile in which to log downtime (default: ./downtime_log.txt)
  --interval <span>    The ping interval in seconds, or use a suffix (E.g. '1m'):
                           's': Seconds
                           'm': Minutes
                           'h': Hours
                           'd': Days
                           'w': Weeks
                        (default: 15s)
  --threshold <ms>     The 'warning' latency threshold for logging (in ms). If this threshold is
                       exceeded, a log entry will be made. (default: 100)
  --window <span>      The graph window in seconds, or use a suffix (E.g. '2d'):
                           's': Seconds
                           'm': Minutes
                           'h': Hours
                           'd': Days
                           'w': Weeks
                        (default: 24h)
  --dark               Enable dark mode (default: False)
  --log-level <level>  Sets the logging level and must be one of:
                         CRITICAL, FATAL, ERROR, WARNING, INFO, DEBUG, NOTSET
                       If not specified, the environment variable "LOGLEVEL" will be used (if set).
                       (default: ERROR)
```
