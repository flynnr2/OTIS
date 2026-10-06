"""PTY-only serial adapter for the isolated host operational rehearsal.

macOS PTYs do not implement modem-control ioctls, so pyserial cannot set DTR
on one. The production recorder and CLI are unchanged; this adapter replaces
only the OS serial descriptor in the synthetic subprocess.
"""

import os
import select
import termios

import serial


class PtySerial:
    def __init__(self, *, port=None, baudrate=115200, timeout=0.1,
                 write_timeout=0.5, exclusive=True):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.exclusive = exclusive
        self.dtr = True
        self.rts = False
        self.fd = None

    def open(self):
        if self.fd is not None:
            raise OSError("PTY port is already open")
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def read(self, size):
        if self.fd is None:
            raise OSError("PTY port is closed")
        if not select.select([self.fd], [], [], self.timeout)[0]:
            return b""
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return b""

    def write(self, data):
        if self.fd is None:
            raise OSError("PTY port is closed")
        if not select.select([], [self.fd], [], self.write_timeout)[1]:
            raise TimeoutError("PTY serial write deadline")
        return os.write(self.fd, data)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


serial.Serial = PtySerial
