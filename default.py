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

import threading
from timeit import default_timer as timer
import xbmc
import xbmcgui
import json
from resources.lib.utils.kodilogging import KodiLogger

log = KodiLogger.log


class VideoInfo(object):
    def __init__(self):
        self.height = 0
        self.width = 0
        self.framerate = 0


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
            if isinstance(self.capture_thread, threading.Thread):
                if self.capture_thread.is_alive:
                    self.capture_thread.join(5)
                if self.capture_thread.is_alive:
                    log(msg='Error')
                    return
            self.capture_thread = CaptureThread(videoinfo)
            self.capture_thread.start()

    def onPlayBackEnded(self):
        if isinstance(self.capture_thread, CaptureThread):
            self.capture_thread.abort()
        self.capture_thread = None

    def onPlayBackStopped(self):
        self.onPlayBackEnded()


class CaptureThread(threading.Thread):
    def __init__(self, videoinfo):
        super(CaptureThread, self).__init__(name='Capture')
        self.videoinfo = videoinfo
        self.rc = xbmc.RenderCapture()
        self.abort_evt = threading.Event()
        if hasattr(self.rc, 'waitForCaptureStateChangeEvent'):
            self.legacy = True
        else:
            self.legacy = False

    def run(self):
        counter = 0
        time0 = timer()
        timeout = 1000
        width = self.videoinfo[0] / 2
        height = self.videoinfo[1] / 2
        log(msg='starting capture w=%i, h=%i' % (width, height))
        result = {}
        result0 = {}
        if self.legacy:
            self.rc.capture(width, height, xbmc.CAPTURE_FLAG_CONTINUOUS)
            capturefn = self.get_frameL
        else:
            capturefn = self.get_frameK
        for loopsleep in range(20, 0, -1):
            log(msg='xbmc.sleep(%i)' % loopsleep)
            for timeout in xrange(100, -1, -10):
                for i in xrange(1, 11):
                    if self.abort_evt.is_set():
                        return
                    t0 = timer()
                    image = capturefn(timeout, width, height)
                    te = timer() - t0
                    result0[i] = [loopsleep, te, len(image)]
                    counter += 1
                    xbmc.sleep(loopsleep)
                result[timeout] = result0

        elapsed = timer() - time0
        log(msg='timeout = %s' % timeout)
        log(msg='counter = %s' % counter)
        log(msg='elapsed = %s' % elapsed)
        log(msg='framerate = %s' % str(counter / elapsed))
        self.printresult(result)
        xbmcgui.Dialog().notification('testRenderCapture', 'DONE')

    def printresult(self, result):
        with open(r'C:\Temp\output.txt', 'w') as f:
            for loopsleep in range (20, 0, -1):
                for timeout in xrange(100, -1, -10):
                    result0 = result[timeout]
                    for i in xrange(1, 11):
                        f.write('%i,%i,%i,%s,%i\n' % (timeout, i, result0[i][0], str(result0[i][1]), result0[i][2]))

    def get_frameK(self, timeout, width, height):
        try:
            self.rc.capture(width, height)
            image = self.rc.getImage(timeout)
        except Exception as e:
            log(msg='Exception: %s' % str(e))
            return bytearray(b'')
        else:
            return image

    def get_frameL(self, timeout, width, height):
        try:
            self.rc.waitForCaptureStateChangeEvent(15)
            cs = self.rc.getCaptureState()
            if cs == xbmc.CAPTURE_STATE_DONE:
                image = self.rc.getImage()
            else:
                return bytearray(b'')
        except Exception as e:
            log(msg='Exception: %s' % str(e))
            return bytearray(b'')
        else:
            return image

    def abort(self):
        self.abort_evt.set()
        if self.is_alive():
            self.join(3)


# class CaptureMonitorThread(threading.Thread):
#
#     def __init__(self, videoinfo, changesleepQ):
#         super(CaptureMonitorThread, self).__init__(name='CaptureMonitor')
#         self.videoinfo = videoinfo
#         self.changesleepQ = changesleepQ
#         self.abort_evt = threading.Event()
#         self.screenshot = threading.Event()
#         self.imageQ = Queue.Queue()
#         self.timestart = None
#         self.framecounter = 0
#         self.droppedframes = 0
#
#     def run(self):
#         delay = 0
#         self.abort_evt.clear()
#         self.screenshot.clear()
#         while not self.abort_evt.is_set():
#             while not self.imageQ.empty():
#                 try:
#                     image, ts = self.imageQ.get(block=True, timeout=1)
#                 except Queue.Empty:
#                     pass
#                 else:
#                     l = len(image)
#                     if l == 0:
#                         self.droppedframes += 1
#                     else:
#                         elapsed = timer() - ts
#                         delay = delay + elapsed
#                         self.framecounter += 1
#                         if self.screenshot.is_set():
#                             pass
#                         xbmc.sleep(5)
#         log(msg = 'totaldelay = %s' % delay)
#         log(msg = 'framecount = %s' % self.framecounter)
#         log(msg='dropped = %s' % self.droppedframes)
#         log(msg='delay = %s' % str(delay/self.framecounter))
#
#     def abort(self):
#         self.abort_evt.set()
#         if self.is_alive():
#             self.join(3)

if __name__ == '__main__':
    KodiLogger.setLogLevel(KodiLogger.LOGNOTICE)
    log(msg='Starting Up')
    p = Player()
    m = xbmc.Monitor()
    m.waitForAbort()
