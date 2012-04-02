#!/usr/bin/env python

"""
Reference:
nsjtpd
http://rubyforge.org/projects/nsjtpd/

Twisted FTP
http://twistedmatrix.com/trac/browser/tags/releases/twisted-12.0.0/twisted/protocols/ftp.py
"""

"""\[Info]
Version=4.0
ScannerName=116.sense
ScannerModelName=HP 9100C
Sender=TYMM
Title=test
ScnSettingType=1
ScnSettingName=COLOR DOCUMENT
Pages=1
Compression=0
Format=5
Duplex=0
Status=0
ApplicationName=
ApplicationItem=
ApplicationTag=
ApplicationPath=
"""

import os
import sys
import tempfile

from twisted.internet import protocol, reactor, interfaces, defer
from twisted.protocols import basic
from twisted.python import log, failure, filepath


output_dir = '/tmp'


class PortConnectionError(Exception):
    pass

class HPNSSDataConnection(object, protocol.Protocol):

    isConnected = False
    bytesRemaining = 0
    receivedFiles = []
    fileInProgress = None

    _fh = None
    _onConnLost = None

    def connectionMade(self):
        log.msg("(Data Connection): Connected.")
        self.isConnected = True
        self.factory.deferred.callback(None)

    def connectionLost(self, reason):
        self.isConnected = False
        if self._fh:
            self._fh.close()
            self._fh = None

        if self._onConnLost is not None:
            self._onConnLost.callback(None)

    def dataReceived(self, data):
        log.msg("Received %d bytes" % len(data))
        self._fh.write(data)
        self.bytesRemaining -= len(data)
        if self.bytesRemaining <= 0:
            self._fh.close()
            self.receivedFiles.append(self.fileInProgress)
            self.fileInProgress = None
            if self.fileDoneCallback:
                self.fileDoneCallback(None)

    def setFileInfo(self, fileName, fileSize, fileType, callback):
        log.msg("Set to receive file: %s %d" % (fileName, fileSize))
        if self.bytesRemaining:
            return None

        if fileType == 'PDF':
            suffix = '.pdf'
        elif fileType == 'TIF':
            suffix = '.tiff'
        else:
            suffix = ''

        fileno, self.fileInProgress = tempfile.mkstemp(dir=output_dir, suffix=suffix)
        self._fh = os.fdopen(fileno, 'w')
        self.bytesRemaining = fileSize

        self.fileDoneCallback = callback


class HPNSSDataConnFactory(protocol.ClientFactory):

    def __init__(self, pi, peerHost = None, reactor = None):
        self.pi = pi
        self.peerHost = peerHost
        self._reactor = reactor
        self.deferred = defer.Deferred()

    def buildProtocol(self, addr):
        log.msg("HPNSSDataConnFactory.buildProtocol %s" % (str(addr)))
        p = HPNSSDataConnection()
        p.factory = self
        p.pi = self.pi
        self.pi.dataInstance = p
        return p

    def clientConnectionFailed(self, connector, reason):
        d, self.deferred = self.deferred, None
        d.errback(PortConnectionError(reason))


class HPNSSProtocol(basic.LineReceiver):

    delimiter = "\r\n"
    dataTimeout = 10
    dataPort = None
    dataFactory = None
    dataInstance = None
    queuedNssPages = []

    def cleanupData(self):
        dataPort, self.dataPort = self.dataPort, None

        if interfaces.IConnector.providedBy(dataPort):
            dataPort.disconnect()

        self.dataFactory.stopFactory()
        self.dataFactory = None

        if self.dataInstance is not None:
            self.dataInstance = None

    def reply(self, line):
        self.transport.write(line)
        self.transport.write(HPNSSProtocol.delimiter)
        log.msg("-> %s" % (line))

    def cmdLogin(self, param):
        log.msg("LOGIN %s" % (str(param)))
        self.reply("23 scanner accepted.")

    def cmdQuit(self, param):
        log.msg("QUIT %s" % (str(param)))
        self.reply("22 scanner connection quitted.")
        self.transport.loseConnection()
        self.disconnected = True

    def cmdPort(self, param):
        log.msg("PORT %s" % (str(param)))
        port = int(param[0]) * 256
        port |= int(param[1])

        self.reply("22 port command successful.")
        self.dataPortNumber = port

    def nssCmdBegindoc(self, param):
        log.msg("NSS BEGINDOC %s" % (str(param)))
        if self.dataFactory is not None:
            self.cleanupData()

        self.reply("23 ready to receive document.")

        peerHost = self.transport.getPeer().host
        self.dataFactory = HPNSSDataConnFactory(pi=self, peerHost=peerHost)

        def connMade(results):
            if self.queuedNssPages:
                self.nssCmdPage(self.queuedNssPages.pop())

        self.dataFactory.deferred.addCallback(connMade)
        self.dataPort = reactor.connectTCP(peerHost, self.dataPortNumber, self.dataFactory)

        log.msg("Connecting to %s:%s" % (str(peerHost), str(self.dataPortNumber)))

    def nssCmdPage(self, param):
        log.msg("...")
        log.msg("NSS PAGE %s" % (str(param)))
        fileSize, fileType, fileName = param

        def fileDoneCB(results):
            self.reply("25 file transfer successful.")

        if self.dataInstance and self.dataInstance.isConnected:
            log.msg("is connected")
            self.dataInstance.setFileInfo(fileName, int(fileSize), fileType, fileDoneCB)
            self.reply("15 starting file transfer of document page.")
        else:
            log.msg("Deferring PAGE -> dataInstance is %s" % str(self.dataInstance))
            self.queuedNssPages.append( ( fileSize, fileType, fileName ) )

    def nssCmdEnddoc(self, param):
        log.msg("NSS ENDDOC %s" % (str(param)))
        header_size = int(param[0])

        def fileDoneCB(results):
            self.reply("25 file transfer successful.")

        self.dataInstance.setFileInfo("header", header_size, "hdr", fileDoneCB)
        self.reply("15 starting file transfer of document header.")

    def nssCmdLog(self, param):
        log.msg("NSS LOG %s" % (str(param)))
        self.reply("23 NSS LOG processed.")

        for file in self.dataInstance.receivedFiles:
            print file

    def lineReceived(self, line):
        param = line.split('\x00')

        if param:
            cmd = param.pop(0)
            if cmd == 'LOGIN':
                self.cmdLogin(param)
            elif cmd == 'QUIT':
                self.cmdQuit(param)
            elif cmd == 'PORT':
                self.cmdPort(param)
            elif cmd == 'NSS':
                nssCmd = param.pop(0)
                if nssCmd == 'BEGINDOC':
                    self.nssCmdBegindoc(param)
                elif nssCmd == 'PAGE':
                    self.nssCmdPage(param)
                elif nssCmd == 'ENDDOC':
                    self.nssCmdEnddoc(param)
                elif nssCmd == 'LOG':
                    self.nssCmdLog(param)
                elif nssCmd == 'ABORTDOC':
                    self.cleanupData()
                else:
                    log.msg("Unknown NSS command (%s)" % (str(param)))
            else:
                log.msg("Unknown Command (%s)" % (str(param)))


class HPNSSFactory(protocol.Factory):

    protocol = HPNSSProtocol


def main():
    import optparse

    log.startLogging(sys.stdout, 0)

    parser = optparse.OptionParser()
    parser.add_option('-p', '--port', dest='port', type='int', default=1687)
    parser.add_option('-d', '--output-dir', dest='output_dir', default='/tmp')
    (opts, args) = parser.parse_args()

    outputDir = opts.output_dir

    reactor.listenTCP(opts.port, HPNSSFactory())
    reactor.run()



if __name__ == '__main__':
    main()
