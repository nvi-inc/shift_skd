Schedule shifting (shift_skd)
---------------------------------------

shift_skd can be used to shift or rotate intensives or 24H VLBI sessions.

Usage: shift_skd.py [-h] [-r] [--reverse] in_path out_path shift [length]

positional arguments:
  in_path       input schedule
  out_path      output schedule
  shift         Number of days to shift or start date
  length        Length in hours

options:
  -h, --help    show this help message and exit
  -r, --rotate  rotate
  --reverse     reverse (valid only with intensive)

The -r option will rotate the schedule for a certain number of days. 
The start will be earlier than original schedule by few minutes every day. 
The ending time will be 24h later. 

If no -r option the schedule will start at the specified time.
The schedule is rotated by specified days and the scans before the start time are dropped.
This shifted schedule will be shorter so the software fill the end of schedule with scans that were dropped 
at beginning (shifted by 24h). 

For intensive, the software is repeating a pattern from the schedule starting with the last source of the schedule.
If the --reverse option is set, the software fill the end of the schedule by repeating the last sources in reverse order.

