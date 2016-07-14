#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#     Copyright (C) 2016 KenV99
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#
from collections import deque

import queue

try:
    import xbmc
except ImportError:
    from time import sleep
    import multiprocessing as foo

    bar = foo.Process
    foobar = foo.ProcessError
else:
    import threading as foo

    bar = foo.Thread
    foobar = foo.ThreadError


class RollingStats(bar):
    def __init__(self, expected_mean=0.0, windowsize=0, sleepinsecs=0.0001):
        super(RollingStats, self).__init__(name='RollingStats')
        self.lock = foo.Lock()
        self.abort_evt = foo.Event()
        self.valueQ = queue.Queue()
        self.mean = float(expected_mean)
        self.sleepinsec = sleepinsecs
        self.n = 0
        self.M2 = 0.0
        if windowsize > 0:
            self.window = windowsize
            self.values = deque()
            self.calc = self.calc_window
        else:
            self.calc = self.calc_nowindow
        try:
            from xbmc import sleep
            self.using_xbmc = True
            self.sleepfn = sleep
        except ImportError:
            from time import sleep
            self.using_xbmc = False
            self.sleepfn = sleep
        self.start()

    def sleep(self):
        if self.using_xbmc:
            self.sleepfn(self.sleepinsec * 1000.0)
        else:
            self.sleepfn(self.sleepinsec)

    def stop(self, timeout=5):
        self.abort_evt.set()
        if self.is_alive():
            try:
                self.join(timeout)
            except foobar:
                pass

    def add_value(self, value):
        with self.lock:
            self.valueQ.put_nowait(value)

    def get_mean(self):
        with self.lock:
            return self.mean

    def get_variance(self, population=False):
        with self.lock:
            if self.window:
                denominator = self.window
            else:
                denominator = self.n
            if population:
                return self.M2 / denominator
            else:
                return self.M2 / (denominator - 1)

    def calc_window(self, value):
        self.values.append(value)
        if self.n < self.window:
            self.n += 1
            d = value - self.mean
            self.mean += d / self.n
            self.M2 += d * (value - self.mean)
        else:
            valueo = self.values.popleft()
            meano = self.mean
            self.mean += (value - valueo) / self.window
            self.M2 += (value - meano) * (value - self.mean) - (valueo - meano) * (valueo - self.mean)

    def calc_nowindow(self, value):
        self.n += 1
        d = value - self.mean
        self.mean += d / self.n
        self.M2 += d * (value - self.mean)

    def run(self):
        while not self.abort_evt.is_set():
            while not self.valueQ.empty():
                with self.lock:
                    value = self.valueQ.get_nowait()
                    self.calc(value)
            else:
                self.sleep()


if __name__ == '__main__':
    import numpy

    lst = [float(i) for i in xrange(-100, 101)]
    windowsize = 10
    rs = RollingStats(expected_mean=0.0, windowsize=windowsize)
    record = {}
    for i, v in enumerate(lst):
        rs.add_value(v)
        if i >= windowsize:
            record[i] = (rs.get_mean(), rs.get_variance(True), v)
    rs.stop()
    for i, v in enumerate(lst):
        if i >= windowsize:
            window = lst[i - windowsize:i]
            print i, record[i][2], record[i][0], numpy.mean(window), record[i][1], numpy.var(window)
