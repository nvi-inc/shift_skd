#!/usr/bin/env python3
import re
import sys

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union, List, Tuple

fmts = ("%y%j%H%M%S", "%Y%j%H%M%S")


class SkdShifter:
    def __init__(self, in_path: Path, out_path: Path, skd_shift: Union[int, datetime] , skd_len: int, rotate: bool,
                 reverse: bool):
        self.in_path, self.out_path = in_path, out_path
        self.exper = out_path.stem
        self._in = self._out = None
        self.start, self.end = datetime.now(), datetime.now()
        self.skd_shift, self.skd_start = skd_shift, datetime.now()
        self.skd_len = skd_len
        self.offset = timedelta(days=0)
        self.rotate, self.reverse = rotate, reverse
        self.slew_time = {}
        self.duration = timedelta(hours=1)

    @staticmethod
    def sk2time(text: str) -> datetime:
        for fmt in fmts:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        raise Exception(f'Invalid time format {text}')

    def copy(self, line: str) -> str:
        self._out.write(line)
        for line in self._in:
            if line.startswith('$'):
                return line
            else:
                self._out.write(line)
        return ''

    def stations(self, line: str) -> str:
        self._out.write(line)
        for line in self._in:
            if line.startswith('$'):
                return line
            self._out.write(line)
            if line.startswith('A') and 'AZEL' in line:  # Process only AZEL antenna
                info = line.split()
                az_slew, el_slew = 360.0 / float(info[5]) * 60.0, 90.0 / float(info[9]) * 60
                self.slew_time[info[1]] = timedelta(seconds=max(az_slew, el_slew))
        return ''

    def param(self, line: str) -> str:
        self._out.write(line)
        for line in self._in:
            if line.startswith('$'):
                return line
            if line.startswith('SCHEDULE_CREATE_DATE'):
                self._out.write(f"SCHEDULE_CREATE_DATE {datetime.now().strftime(fmts[0])}\n")
            elif line.startswith('SCHEDULER'):
                words = line.split()
                start, end = self.sk2time(old_start := words[-3]), self.sk2time(words[-1])
                self.duration = (end - start)
                skd_len = timedelta(hours=self.skd_len) if self.skd_len else self.duration
                if skd_len > self.duration:
                    raise Exception('New schedule length greater than duration')
                if isinstance(self.skd_shift, datetime):
                    skd_shift = (self.skd_shift - start).total_seconds() / 86400.0
                    if self.rotate:  # Use only date
                        skd_shift = float((self.skd_shift.date() - start.date()).days)
                        print(f'Using {skd_shift} days for rotation')
                else:
                    skd_shift = self.skd_shift

                self.offset = timedelta(days=(365.2422 / 366.2422 * skd_shift))

                if self.rotate:
                    self.start, action = start + self.offset, 'Rotating'
                else:
                    self.start, action = start + timedelta(days=skd_shift), 'Shifting'

                self.end = self.start + skd_len
                words[-3], words[-1] = self.start.strftime(fmts[0]), self.end.strftime(fmts[0])
                dur = int((self.end - self.start).total_seconds() / 3600 + 0.2)
                print(f"{action} schedule from {old_start} to {words[-3]}. Length {dur} hour{'s' if dur > 1 else ''}")
                self._out.write(f"{' '.join(words)}\n")
            else:
                self._out.write(line)
        return ''


    def complete_standard(self, records: List[Tuple[str, datetime, re.Match[str]]]):
        def skip_record():
            codes = match['after'].split()[4]
            # Checks if all stations have time to slew to this scan.
            for sta_id in [codes[i] for i in range(0, len(codes), 2)]:
                for _, t, rec in records[::-1]:
                    rec_info = rec['after'].split()
                    rec_codes = rec_info[4]
                    if sta_id in [rec_codes[i] for i in range(0, len(rec_codes), 2)]:
                        if time_tag <= (t + timedelta(seconds=float(rec_info[0])) + self.slew_time[sta_id]):
                            return True
                        break
            return False

        offset = timedelta(days=1)
        test_slew = True
        for _, time_tag, match in records:
            if (time_tag := time_tag + offset) > self.end:
                return
            if test_slew:
                if skip_record():
                    continue
                test_slew = False
            self._out.write(f"{match['before']}{time_tag.strftime(fmts[0])}{match['after']}\n")

    def complete_intensive(self, records: List[Tuple[str, datetime, re.Match[str]]]):

        counts = Counter([src for src, *_ in records])
        last_src, t0, _ = records[-1]
        if counts[last_src] > 1 and not self.reverse:  # make sure the source is there more than once
            for index, (src, time_tag, _) in enumerate(records):
                if src == last_src:  # Find the first record with this source
                    for nbr in range(3):
                        t = t0
                        for i in range(index + 1, len(records)):
                            src, t, match = records[i]
                            if (t := t0 + (t - time_tag)) > self.end:
                                return
                            self._out.write(f"{match['before']}{t.strftime(fmts[0])}{match['after']}\n")
                        t0 = t
                    return
        else:  # This source is only once in the schedule
            for src, time_tag, match in records[-2::-1]:
                if (t := t0 + (t0 - time_tag)) > self.end:
                    return
                self._out.write(f"{match['before']}{t.strftime(fmts[0])}{match['after']}\n")

    def sked(self, line: str):
        skd_rec = re.compile(r"(?P<before>.*)(?P<time>\d{11})(?P<after>.*)").match
        records = []

        self._out.write(line)
        for line in self._in:
            if line.startswith('$'):
                if not self.rotate:
                    if self.duration > timedelta(hours=23):
                        self.complete_standard(records)
                    else:
                        self.complete_intensive(records)
                return line
            if match := skd_rec(line):
                time_tag = self.sk2time(match['time']) + self.offset
                src = match['before'].split()[0]
                records.append((src, time_tag, match))
                if self.start <= time_tag <= self.end:
                    self._out.write(f"{match['before']}{time_tag.strftime(fmts[0])}{match['after']}\n")
            else:
                self._out.write(line)
        return ''

    def process(self):
        fnc = {'$PARAM': self.param, '$SKED': self.sked, '$STATIONS': self.stations}
        with open(self.in_path, 'r', errors='ignore') as self._in, open(self.out_path, 'w') as self._out:
            line = self._in.readline()  # Read EXPER
            self._out.write(f"{line.split()[0]} {self.exper.upper()}\n")
            line = self._in.readline()  # Read EXPER
            while True:
                if not (line := fnc.get(line.split()[0], self.copy)(line)):
                    break


if __name__ == '__main__':
    import argparse

    def validate_shift(text: str) -> Union[int, datetime]:
        try:  # Test if number of days
            return int(text.strip())
        except ValueError:
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                raise argparse.ArgumentTypeError('Invalid shift')

    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--rotate', help='rotate', action='store_true')
    parser.add_argument('--reverse', help='reverse', action='store_true')
    parser.add_argument('in_path', help='input schedule')
    parser.add_argument('out_path', help='output schedule')
    parser.add_argument('shift', help='Number of days to shift or start date', type=validate_shift)
    parser.add_argument('length', help='Length in hours', type=int, nargs='?', default=0)

    args = parser.parse_args()

    if not (p_in := Path(args.in_path)).exists():
        print(f"{args.in_path} does not exist")
        sys.exit(1)
    if (p_out := Path(args.out_path)).exists():
        while True:
            rsp = input(f"{p_out} already exist! Overwrite it? (Y/n) ")
            if rsp.startswith(('n', 'N')):
                sys.exit(0)
            if not rsp or rsp.startswith(('y', 'Y')):
                break

    try:
        skd = SkdShifter(p_in, p_out, args.shift, args.length, args.rotate, args.reverse)
        skd.process()
    except Exception as err:
        print(f'Terminated! {str(err)}')




