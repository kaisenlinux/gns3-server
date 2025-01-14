#
# Copyright (C) 2014 GNS3 Technologies Inc.
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

"""
ATM port for ATM link end points.
"""

from .serial_port import SerialPort


class ATMPort(SerialPort):
    @staticmethod
    def long_name_type():
        """
        Returns the long name type for this port.

        :returns: string
        """
        return "ATM"

    @staticmethod
    def short_name_type():
        """
        Returns the short name type for this port.

        :returns: string
        """
        return "a"

    @property
    def data_link_types(self):
        """
        Returns the supported PCAP DLTs.

        :return: dictionary
        """

        return {"ATM": "DLT_ATM_RFC1483"}
