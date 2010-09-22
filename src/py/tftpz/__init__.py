from gevent import monkey; monkey.patch_all()

import socket
import sys
import logging
from SocketServer import UDPServer, ThreadingMixIn, BaseRequestHandler
from itertools import count

from restkit import request, RedirectLimit
from daemonhelper import Daemon, make_main
from dpkt.tftp import *
from dpkt.udp import *

class TftpException(Exception):
	@classmethod
	def from_other_exception(cls, pyexception):
		return cls(EUNDEF, str(pyexception))

	def __init__(self, code, message):
		self.code = code
		self.message = message
		Exception.__init__(self, code, message)

class TftpzHandler(BaseRequestHandler):
	_max_send_tries = 4

	def __init__(self, *args, **kwargs):
		BaseRequestHandler.__init__(self, *args, **kwargs)

	def _send_data(self, sock, addr, data, block):
		pkt = TFTP()
		pkt.opcode = OP_DATA
		pkt.block = block
		
		pkt.data = data
		
		for _ in xrange(self._max_send_tries):
			sock.sendto(str(pkt), 0, addr)
			
			try:
				self._wait_for_ack(sock, block)
				return
			except socket.timeout:
				continue

		raise TftpException(EUNDEF, "timed out")

	def _wait_for_ack(self, sock, blocknum):
		while True:
			recv_str, recv_addr = sock.recvfrom(1024)
			ack = TFTP(recv_str)
			if ack.opcode == OP_ACK and ack.block[0] == blocknum:
				return

	def _send_file(self, sock, addr, fileobj):
		for block in count(1):
			data = fileobj.read(512)
			self._send_data(sock, addr, data, block)
			if len(data) < 512:
				break

	def _send_error(self, sock, logger, e):
		logger.debug("client %s:%d got error %d %r" % (self.client_address + (e.code, e.message)))

		pkt = TFTP()
		pkt.opcode = OP_ERR
		pkt.errcode = e.code
		pkt.errmsg = e.message
		sock.sendto(str(pkt), 0, self.client_address)
		
	def handle(self):
		logger = self.server.logger
		data = self.request[0]
		packet = TFTP(data)

		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.bind((self.server.host, 0))
		sock.settimeout(1)

		try:
			if packet.opcode == OP_RRQ:
				handler = self.handle_get
			else:
				raise ValueError("opcode %d is not supported" % packet.opcode)

			handler(sock, packet, logger)
		except TftpException, e:
			self._send_error(sock, logger, e)
		except Exception, e:
			e2 = TftpException.from_other_exception(e)
			self._send_error(sock, logger, e2)
		
	def handle_get(self, sock, packet, logger):
		filename = packet.filename.strip('/')

		logger.info("client %s:%d requested %r" % (self.client_address + (filename,)))

		url = "%s/%s" % (self.server.baseurl, filename)

		req = request(url, follow_redirect=True)
		status = req.status_int

		if 200 <= status < 300:
			self._send_file(sock, self.client_address, req.body_stream())

		elif status == 404:
			raise TftpException(ENOTFOUND, "file not found")
		else:
			raise TftpException(EUNDEF, "unknown HTTP error %d" % status)
	
class TftpzServer(ThreadingMixIn, UDPServer):
	def __init__(self, address=('0.0.0.0', 69), baseurl="http://127.0.0.1", handler=TftpzHandler, logger=None):
		UDPServer.__init__(self, address, handler)
		
		self.logger = logger or logging.getLogger()
		self.handler = handler
		self.baseurl = baseurl

		self.host, self.port = address

class TftpzDaemon(Daemon):
	name = "tftpz"
	description = "Proxies TFTP requests to HTTP servers"

	_server = None

	def handle_prerun(self):
		listen = self.config("tftpz", "listen", "0.0.0.0")
		baseurl = self.config("tftpz", "baseurl", "http://127.0.0.1")
		self._server = TftpzServer((listen, 69), baseurl=baseurl, logger=self.logger)

	def handle_run(self):
		self._server.serve_forever()

	def handle_stop(self):
		if self._server is not None:
			self._server.shutdown()

main = make_main(TftpzDaemon)

if __name__ == "__main__":
	main()
