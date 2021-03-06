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
debug = False

from resources.lib.utils.debugger import startdebugger

if debug:
    startdebugger()

import sys
import os
import threading
import Queue
from timeit import default_timer as timer
import xbmc
import xbmcgui
import json
from resources.lib.utils.kodilogging import KodiLogger

log = KodiLogger.log


class Player(xbmc.Player):
    def __init__(self):
        super(Player, self).__init__()
        self.capture_thread = None
        self.info = None

    def getVideoInfo(self, playerid):
        try:
            info = json.loads(xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "method": "Player.GetItem", "params": { "properties": ["title", "album",'
                ' "artist", "season", "episode", "duration", "showtitle", "tvshowid", "file",  "streamdetails"],'
                ' "playerid": %s }, "id": "VideoGetItem"}' % playerid))['result']['item']
        except RuntimeError:
            self.info = {}
        else:
            items = [u'label', u'id', u'tvshowid']
            for item in items:
                try:
                    del info[item]
                except KeyError:
                    pass
            items = {u'mediaType': u'type', u'fileName': u'file'}
            for item in items.keys():
                try:
                    t = items[item]
                    info[item] = info.pop(t, 'unknown')
                except KeyError:
                    info[item] = u'unknown'
            if info['mediaType'] != 'musicvideo':
                items = [u'artist', u'album']
                for item in items:
                    try:
                        del info[item]
                    except KeyError:
                        pass
            else:
                try:
                    info[u'artist'] = info[u'artist'][0]
                except (KeyError, IndexError):
                    info[u'artist'] = u'unknown'
            if u'streamdetails' in info.keys():
                sd = info.pop(u'streamdetails', {})
                try:
                    info[u'stereomode'] = sd[u'video'][0][u'stereomode']
                except (KeyError, IndexError):
                    info[u'stereomode'] = u'unknown'
                else:
                    if info[u'stereomode'] == u'':
                        info[u'stereomode'] = u'unknown'
                try:
                    info[u'width'] = unicode(sd[u'video'][0][u'width'])
                except (KeyError, IndexError):
                    info[u'width'] = u'unknown'
                try:
                    info[u'height'] = unicode(sd[u'video'][0][u'height'])
                except (KeyError, IndexError):
                    info[u'height'] = u'unknown'
                try:
                    info[u'aspectRatio'] = unicode(int((sd[u'video'][0][u'aspect'] * 100.0) + 0.5) / 100.0)
                except (KeyError, IndexError):
                    info[u'aspectRatio'] = u'unknown'
            if info[u'mediaType'] == u'episode':
                items = [u'episode', u'season']
                for item in items:
                    try:
                        info[item] = unicode(info[item]).zfill(2)
                    except KeyError:
                        info[item] = u'unknown'
            else:
                items = [u'episode', u'season', u'showtitle']
                for item in items:
                    try:
                        del info[item]
                    except KeyError:
                        pass
            self.info = info

    def getInfo(self):
        tries = 0
        while tries < 8 and self.isPlaying() is False:
            xbmc.sleep(250)
        try:
            player = json.loads(xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}'))
        except RuntimeError:
            playerid = -1
            playertype = 'none'
        else:
            try:
                playerid = player['result'][0]['playerid']
                playertype = player['result'][0]['type']
            except KeyError:
                playerid = -1
                playertype = 'none'
        if playertype == 'video':
            self.getVideoInfo(playerid)
        else:
            self.info = {}

    def onPlayBackStarted(self):
        if self.isPlayingVideo():
            self.getInfo()
            videoinfo = [int(self.info['width']), int(self.info['height'])]
            if isinstance(self.capture_thread, threading.Thread):  # Make sure that thread isn't already running
                if self.capture_thread.is_alive:
                    self.capture_thread.join(5)
                if self.capture_thread.is_alive:
                    log(msg='Error')
                    return
            self.capture_thread = CaptureThread(videoinfo, self)
            self.capture_thread.start()

    def onPlayBackEnded(self):
        if isinstance(self.capture_thread, CaptureThread):
            self.capture_thread.abort()
        self.capture_thread = None

    def onPlayBackStopped(self):
        self.onPlayBackEnded()


class BreakLoop(Exception):
    pass


class CaptureThread(threading.Thread):
    '''
    Run the capture routine in a separate thread and call abort if playback ends
    '''

    def __init__(self, videoinfo, player):
        self.player = player
        super(CaptureThread, self).__init__(name='Capture')
        self.videoinfo = videoinfo
        self.rc = xbmc.RenderCapture()
        self.abort_evt = threading.Event()
        self.capture_monitor_thread = CaptureMonitorThread()
        self.resultQ = self.capture_monitor_thread.resultQ
        if hasattr(self.rc, 'waitForCaptureStateChangeEvent'):
            self.legacy = True
        else:
            self.legacy = False
        self.dropped = 0
        self.capture_monitor_thread.start()
        self.dummyQ = Queue.Queue()
        self.lastimage = bytearray(b'')

    def run(self):
        counter = 0
        uniqueframes = 0
        timeout = 1000
        width = self.videoinfo[0] / 2
        height = self.videoinfo[1] / 2
        if self.legacy:
            self.rc.capture(width, height, xbmc.CAPTURE_FLAG_CONTINUOUS)
            capturefn = self.get_frameLegacy
            overheadfn = self.get_frameLegacyOverhead
            log(msg=u'legacy capture')
        else:
            capturefn = self.get_frameKrypton
            overheadfn = self.get_frameKryptonOverhead
            log(msg=u'krypton capture')
        overheadtotal = 0.0
        for i in xrange(0, 100):
            capturesleepms = 5 / 1000
            t0 = timer()
            _ = overheadfn(width, height, 5)
            te = timer() - t0 - capturesleepms
            overheadtotal += te
        overhead = overheadtotal / 100.0
        self.dropped = 0
        log(msg='overhead for capture function: %s ms' % str(overhead * 1000.0))
        log(msg=u'starting capture w=%i, h=%i' % (width, height))
        time0 = timer()
        flagdone = False
        while not self.abort_evt.is_set():
            try:
                # for loopsleep in range(20, -1, -5):  # sleep in between frames
                loopsleep = 5
                # log(msg=u'xbmc.sleep(%i)' % loopsleep)
                capturesleep = 0
                # for capturesleep in xrange(10, -1, -5):  # sleep between capture request and getImage
                capturesleepms = capturesleep / 1000.0
                for timeout in xrange(80, 9, -10):  # timeout parameter for getImage
                    for frame in xrange(1, 251):
                        if self.abort_evt.is_set():
                            raise BreakLoop
                        t0 = timer()
                        image = capturefn(timeout, width, height, sleep=capturesleep)
                        te = timer() - t0 - overhead - capturesleepms  # subtract the amount of xbmc.sleep
                        duplicate = (image == self.lastimage)
                        if not duplicate and len(image) > 1:
                            uniqueframes += 1
                        counter += 1
                        self.resultQ.put(
                            [t0 - time0, loopsleep, timeout, capturesleep, frame, te, len(image), duplicate])
                        self.lastimage = image
                        xbmc.sleep(loopsleep)  # unclear if this helps avoid GIL issues
            except BreakLoop:
                pass
            if flagdone is False:
                flagdone = True
                xbmcgui.Dialog().notification(u'testRenderCapture', u'Adequate data gathered for analysis')
        elapsed = timer() - time0
        self.capture_monitor_thread.abort(totalelapsed=elapsed)
        log(msg=u'timeout = %s' % timeout)
        log(msg=u'counter = %s' % counter)
        log(msg=u'dropped = %s' % self.dropped)
        log(msg=u'elapsed = %s' % elapsed)
        log(msg=u'framerate = %s' % str(counter / elapsed))
        log(msg=u'uniqueframerate = %s' % str(uniqueframes / elapsed))

        xbmcgui.Dialog().notification(u'testRenderCapture', u'DONE')

    def get_fromqueue(self, timeout, width, height, sleep=0):
        try:
            if sleep > 0:
                xbmc.sleep(sleep)  # unclear if this helps avoid GIL issues
            try:
                self.dummyQ.get(block=True, timeout=timeout / 1000.0)
            except Queue.Empty:
                pass
            image = bytearray('b')
        except Exception as e:
            log(msg=u'Exception: %s' % unicode(e))
            return bytearray(b'')
        else:
            if len(image) == 0:
                self.dropped += 1
            return image

    def get_frameKrypton(self, timeout, width, height, sleep=0):
        try:
            self.rc.capture(width, height)
            if sleep > 0:
                xbmc.sleep(sleep)  # unclear if this helps avoid GIL issues
            image = self.rc.getImage(timeout)
        except Exception as e:
            log(msg=u'Exception: %s' % unicode(e))
            return bytearray(b'')
        else:
            if len(image) == 0:
                self.dropped += 1
            return image

    def get_frameLegacy(self, timeout, width, height, sleep):
        try:
            self.rc.waitForCaptureStateChangeEvent(timeout)
            cs = self.rc.getCaptureState()
            if cs == xbmc.CAPTURE_STATE_DONE:
                image = self.rc.getImage()
            else:
                self.dropped += 1
                return bytearray(b'')
        except Exception as e:
            log(msg=u'Exception: %s' % str(e))
            return bytearray(b'')
        else:
            return image

    def get_frameKryptonOverhead(self, timeout, width, height, sleep=0):
        try:
            pass  # self.rc.capture(width, height)
            if sleep > 0:
                xbmc.sleep(sleep)  # unclear if this helps avoid GIL issues
            image = bytearray(b' ')  # image = self.rc.getImage(timeout)
        except Exception as e:
            log(msg=u'Exception: %s' % unicode(e))
            return bytearray(b'')
        else:
            if len(image) == 0:
                self.dropped += 1
            return image

    def get_frameLegacyOverhead(self, timeout, *_):
        try:
            pass  # self.rc.waitForCaptureStateChangeEvent(timeout)
            cs = xbmc.CAPTURE_STATE_DONE  # cs = self.rc.getCaptureState()
            if cs == xbmc.CAPTURE_STATE_DONE:
                image = bytearray(b' ')  # image = self.rc.getImage()
            else:
                self.dropped += 1
                return bytearray(b'')
        except Exception as e:
            log(msg=u'Exception: %s' % str(e))
            return bytearray(b'')
        else:
            return image

    def abort(self, timeout=5):
        self.abort_evt.set()
        if self.is_alive():
            self.join(timeout)


class CaptureMonitorThread(threading.Thread):
    '''
    Writes frame by frame results to file.
    Runs in separate thread to avoid possible I/O bound waiting.
    '''

    def __init__(self):
        super(CaptureMonitorThread, self).__init__(name='CaptureMonitor')
        self.abort_evt = threading.Event()
        self.resultQ = Queue.Queue()
        self.totalelapsed = 0

    def run(self):
        self.abort_evt.clear()
        if sys.platform.lower().startswith('win'):
            fn = r'C:\Temp\output.csv'
        else:
            fn = os.path.expanduser(r'~/.kodi/output.csv')
        f = open(fn, 'w', 0)  # '0' buffersize so that line is immediately written to file
        f.write(
            '"playtime","loopsleep","timeout","capturesleep","frame","timeelapsed","imagelength","dup"\n')  # header for import
        timerequestingframes = 0
        while not self.abort_evt.is_set():
            while not self.resultQ.empty():
                try:
                    result = self.resultQ.get(block=True, timeout=1)
                except Queue.Empty:
                    pass
                else:
                    f.write('%s,%i,%i,%i,%i,%s,%i,%s\n' % (
                        "{0:.4f}".format(result[0]), result[1], result[2], result[3], result[4],
                        "{0:.4f}".format(result[5] * 1000.0), result[6], result[7]))
                    timerequestingframes += result[5]
            xbmc.sleep(5)  # unclear if this helps avoid GIL issues
        f.close()
        if self.totalelapsed != 0:
            log(msg=u'Percent time waiting for frames: %s' % "{0:.2f}".format(
                timerequestingframes / self.totalelapsed * 100.0))

    def abort(self, timeout=5, totalelapsed=0):
        self.totalelapsed = totalelapsed
        self.abort_evt.set()
        if self.is_alive():
            self.join(timeout)


if __name__ == '__main__':
    KodiLogger.setLogLevel(KodiLogger.LOGNOTICE)
    log(msg=u'Starting Up')
    p = Player()
    m = xbmc.Monitor()
    m.waitForAbort()
