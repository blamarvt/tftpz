#!/usr/bin/python

import gevent
import logging
import dpkt.tftp as tftp
import gevent.socket as _socket

import tftpz.util

from itertools import count

class TftpException(Exception):
    @classmethod
    def from_other_exception(cls, pyexception):
        return cls(tftp.EUNDEF, str(pyexception))
    
    def __init__(self, code, message):
        self.code = code
        self.message = message
        Exception.__init__(self, code, message)


class TftpNotFoundException(TftpException):
    def __init__(self):
        TftpException.__init__(self, tftp.ENOTFOUND, "Not Found")


class TftpServerListener(gevent.Greenlet):
    """
    Binds to a socket and listens for TFTP requests, calling 
    handle() on the specified handler class. Implemented as 
    a gevent Greenlet.
    """

    _bufsize = 1500
    _max_send_tries = 4

    def __init__(self, ip_address, handler, logger=None):
        """
        @param ip_address: The IP address we're listening on
        @param handler: The class/instance to call handle on
        """
        gevent.Greenlet.__init__(self)

        self.ip_address = ip_address
        self.handler = handler
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        self.iface_name, self.ip_config = tftpz.util.network_config()[ip_address]
        self._keepgoing = True

        self.sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        self.sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BINDTODEVICE, self.iface_name)
        self.sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        self.sock.bind(('', 69))

    def _run(self):
        """
        Primary logic function which is the entry point for the listener.
        """
        while self._keepgoing:
            data, (host, port) = self.sock.recvfrom(self._bufsize)
            packet = tftp.TFTP(data)
            gevent.spawn(self._handle_packet, packet, (host, port))


    def _handle_packet(self, packet, (host, port)):
        if packet.opcode == tftp.OP_RRQ:
            handler = getattr(self, "_handle_get", None)
        else:
            handler = None

        if handler: 
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                sock.bind((self.ip_address, 0))
                sock.settimeout(1)
            
                handler(sock, (host, port), packet)
                
            except TftpException as ex:
                #self.logger.debug("TftpException: %r" % ex)
                self._send_error(sock, ex, (host, port))

            except Exception as ex:
                self.logger.error("Uncaught Exception: %r" % ex)
                ex2 = TftpException.from_other_exception(ex)
                self._send_error(sock, ex2, (host, port))
                raise

    def stop(self):
        self._keepgoing = False
        self.kill()

    def _handle_get(self, sock, (host, port), packet):
        """
        Wrapper method around the true handle_get.

        @param sock: The socket for the host we're handling the request for
        @param host: The host of the requestor
        @param port: The port of the requestor
        @param packet: The TFTP packet
        """
        handler = getattr(self.handler, "handle_get", None)
   
        if handler:
            fileobj = handler(packet.filename)
            self._send_file(sock, (host, port), fileobj)

    def _send_data(self, sock, (host, port), data, block):
        """
        Helper function, called by _send_file which sends a block of data.

        @param sock: The socket we're sending to
        @param host: The host we're sending to
        @param port: The port we're sending to
        @param data: The data we're sending
        @param block: The block we're on (an int)
        """
        pkt = tftp.TFTP()
        pkt.opcode = tftp.OP_DATA
        pkt.block = block
        
        pkt.data = data
        
        for _ in xrange(self._max_send_tries):
            sock.sendto(str(pkt), 0, (host, port))
            
            try:
                self._wait_for_ack(sock, block)
                return
            except _socket.timeout:
                continue

        raise TftpException(tftp.EUNDEF, "timed out")

    def _wait_for_ack(self, sock, blocknum):
        """
        The TFTP RFC says we need to wait for the client to ACK...
        
        @param sock: The sock we're waiting for the ACK on
        @param blocknum: The block number we're waiting for an ACK for
        """
        while True:
            recv_str, recv_addr = sock.recvfrom(1024)
            ack = tftp.TFTP(recv_str)
            if ack.opcode == tftp.OP_ACK and ack.block[0] == blocknum:
                return

    def _send_file(self, sock, (host, port), fileobj):
        """
        Send an entire file to a client, given a file-like object.
        
        @param sock: The socket we're using
        @param host: The host of the client
        @param port: The port of the client
        @param fileobj: The file to be sent
        """
        for block in count(1):
            data = fileobj.read(512)
            self._send_data(sock, (host, port), data, block)
            if len(data) < 512:
                break

    def _send_error(self, sock, e, addr):
        """
        Send an error message back to the client.
        
        @param sock: The socket to use
        @param e: The exception
        """
        #self.logger.debug("client %s:%d got error %d %r" % (addr + (e.code, e.message)))

        pkt = tftp.TFTP()
        pkt.opcode = tftp.OP_ERR
        pkt.errcode = e.code
        pkt.errmsg = e.message
        sock.sendto(str(pkt), 0, addr)
        
    
class TftpServer(object):
    _listener_factory = TftpServerListener

    def __init__(self, handler, logger=None):
        self.handler = handler
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._listeners = []
        self._running = False

    def listen(self, ip_address):
        listener = self._listener_factory(ip_address, self.handler, self.logger)
        self._listeners.append(listener)
        if self._running:
            self._launch_listener(listener)

    def run(self):
        self._running = True
        map(self._launch_listener, self._listeners)
        for listener in self._listeners:
            listener.join()

    def stop(self):
        self._running = False
        for listener in self._listeners:
            listener.stop()

    def _launch_listener(self, listener):
        self.logger.info("listening on %s" % listener.ip_address)
        listener.start()
