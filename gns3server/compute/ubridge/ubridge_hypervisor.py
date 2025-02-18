#
# Copyright (C) 2015 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import time
import logging
import asyncio

from gns3server.utils.asyncio import locking
from .ubridge_error import UbridgeError

log = logging.getLogger(__name__)


class UBridgeHypervisor:

    """
    Creates a new connection to uBridge hypervisor.

    :param host: the hostname or ip address string of the uBridge hypervisor
    :param port: the tcp port integer
    :param timeout: timeout integer for how long to wait for a response to commands sent to the
    hypervisor (defaults to 30 seconds)
    """

    # Used to parse Ubridge response codes
    error_re = re.compile(r"""^2[0-9]{2}-""")
    success_re = re.compile(r"""^1[0-9]{2}\s{1}""")

    def __init__(self, host, port, timeout=30.0):

        self._host = host
        self._port = port
        self._version = "N/A"
        self._timeout = timeout
        self._reader = None
        self._writer = None

    async def connect(self, timeout=10):
        """
        Connects to the hypervisor.
        """

        # connect to a local address by default
        # if listening to all addresses (IPv4 or IPv6)
        if self._host == "0.0.0.0":
            host = "127.0.0.1"
        elif self._host == "::":
            host = "::1"
        else:
            host = self._host

        begin = time.time()
        connection_success = False
        last_exception = None
        while time.time() - begin < timeout:
            await asyncio.sleep(0.1)
            try:
                self._reader, self._writer = await asyncio.open_connection(host, self._port)
            except OSError as e:
                last_exception = e
                continue
            connection_success = True
            break

        if not connection_success:
            raise UbridgeError(f"Couldn't connect to hypervisor on {host}:{self._port} :{last_exception}")
        else:
            log.info(f"Connected to uBridge hypervisor on {host}:{self._port} after {time.time() - begin:.4f} seconds")

        try:
            await asyncio.sleep(0.1)
            version = await self.send("hypervisor version")
            self._version = version[0].split("-", 1)[0]
        except IndexError:
            self._version = "Unknown"

    @property
    def version(self):
        """
        Returns uBridge version.

        :returns: version string
        """

        return self._version

    async def close(self):
        """
        Closes the connection to this hypervisor (but leave it running).
        """

        await self.send("hypervisor close")
        self._writer.close()
        self._reader, self._writer = None

    async def stop(self):
        """
        Stops this hypervisor (will no longer run).
        """

        try:
            # try to properly stop the hypervisor
            await self.send("hypervisor stop")
        except UbridgeError:
            pass
        try:
            if self._writer is not None:
                await self._writer.drain()
                self._writer.close()
        except OSError as e:
            log.debug(f"Stopping hypervisor {self._host}:{self._port} {e}")
        self._reader = self._writer = None

    async def reset(self):
        """
        Resets this hypervisor (used to get an empty configuration).
        """

        await self.send("hypervisor reset")

    @property
    def port(self):
        """
        Returns the port used to start the hypervisor.

        :returns: port number (integer)
        """

        return self._port

    @port.setter
    def port(self, port):
        """
        Sets the port used to start the hypervisor.

        :param port: port number (integer)
        """

        self._port = port

    @property
    def host(self):
        """
        Returns the host (binding) used to start the hypervisor.

        :returns: host/address (string)
        """

        return self._host

    @host.setter
    def host(self, host):
        """
        Sets the host (binding) used to start the hypervisor.

        :param host: host/address (string)
        """

        self._host = host

    @locking
    async def send(self, command):
        """
        Sends commands to this hypervisor.

        :param command: a uBridge hypervisor command

        :returns: results as a list
        """

        # uBridge responses are of the form:
        #   1xx yyyyyy\r\n
        #   1xx yyyyyy\r\n
        #   ...
        #   100-yyyy\r\n
        # or
        #   2xx-yyyy\r\n
        #
        # Where 1xx is a code from 100-199 for a success or 200-299 for an error
        # The result might be multiple lines and might be less than the buffer size
        # but still have more data. The only thing we know for sure is the last line
        # will begin with '100-' or a '2xx-' and end with '\r\n'

        if self._writer is None or self._reader is None:
            raise UbridgeError("Not connected")

        try:
            command = command.strip() + "\n"
            log.debug(f"sending {command}")
            self._writer.write(command.encode())
            await self._writer.drain()
        except OSError as e:
            raise UbridgeError(
                "Lost communication with {host}:{port} when sending command '{command}': {error}, uBridge process running: {run}".format(
                    host=self._host, port=self._port, command=command, error=e, run=self.is_running()
                )
            )

        # Now retrieve the result
        data = []
        buf = ""
        retries = 0
        max_retries = 10
        while True:
            try:
                try:
                    chunk = await self._reader.read(1024)
                except asyncio.CancelledError:
                    # task has been canceled but continue to read
                    # any remaining data sent by the hypervisor
                    continue
                except ConnectionResetError as e:
                    # Sometimes WinError 64 (ERROR_NETNAME_DELETED) is returned here on Windows.
                    # These happen if connection reset is received before IOCP could complete
                    # a previous operation. Ignore and try again....
                    log.warning(f"Connection reset received while reading uBridge response: {e}")
                    continue
                if not chunk:
                    if retries > max_retries:
                        raise UbridgeError(
                            "No data returned from {host}:{port} after sending command '{command}', uBridge process running: {run}".format(
                                host=self._host, port=self._port, command=command, run=self.is_running()
                            )
                        )
                    else:
                        retries += 1
                        await asyncio.sleep(0.5)
                        continue
                retries = 0
                buf += chunk.decode("utf-8")
            except OSError as e:
                raise UbridgeError(
                    "Lost communication with {host}:{port} after sending command '{command}': {error}, uBridge process running: {run}".format(
                        host=self._host, port=self._port, command=command, error=e, run=self.is_running()
                    )
                )

            # If the buffer doesn't end in '\n' then we can't be done
            try:
                if buf[-1] != "\n":
                    continue
            except IndexError:
                raise UbridgeError(
                    "Could not communicate with {host}:{port} after sending command '{command}', uBridge process running: {run}".format(
                        host=self._host, port=self._port, command=command, run=self.is_running()
                    )
                )

            data += buf.split("\r\n")
            if data[-1] == "":
                data.pop()
            buf = ""

            # Does it contain an error code?
            if self.error_re.search(data[-1]):
                raise UbridgeError(data[-1][4:])

            # Or does the last line begin with '100-'? Then we are done!
            if data[-1][:4] == "100-":
                data[-1] = data[-1][4:]
                if data[-1] == "OK":
                    data.pop()
                break

        # Remove success responses codes
        for index in range(len(data)):
            if self.success_re.search(data[index]):
                data[index] = data[index][4:]

        log.debug(f"returned result {data}")
        return data
