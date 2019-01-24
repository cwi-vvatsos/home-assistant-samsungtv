"""
Support for interface with an Samsung TV.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.samsungtv/
"""
import logging
import socket

REQUIREMENTS = ['wakeonlan==0.2.2', 'beautifulsoup4==4.6.0']

from bs4 import BeautifulSoup

import voluptuous as vol

from homeassistant.components.media_player import (
    SUPPORT_SELECT_SOURCE, SUPPORT_TURN_OFF, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP, MediaPlayerDevice, PLATFORM_SCHEMA, SUPPORT_TURN_ON)
from homeassistant.const import (
    CONF_HOST, CONF_NAME, STATE_OFF, STATE_ON, STATE_UNKNOWN, CONF_PORT,
    CONF_MAC)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_TIMEOUT = 'timeout'

DEFAULT_NAME = 'Samsung TV Remote'
DEFAULT_PORT = 55000
DEFAULT_TIMEOUT = 0

KNOWN_DEVICES_KEY = 'samsungtv_known_devices'

SUPPORT_SAMSUNGTV = SUPPORT_SELECT_SOURCE | SUPPORT_VOLUME_SET | \
    SUPPORT_VOLUME_STEP | SUPPORT_VOLUME_MUTE | SUPPORT_TURN_OFF

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Samsung TV platform."""
    known_devices = hass.data.get(KNOWN_DEVICES_KEY)
    if known_devices is None:
        known_devices = set()
        hass.data[KNOWN_DEVICES_KEY] = known_devices

    # Is this a manual configuration?
    if config.get(CONF_HOST) is not None:
        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        name = config.get(CONF_NAME)
        mac = config.get(CONF_MAC)
        timeout = config.get(CONF_TIMEOUT)
    elif discovery_info is not None:
        tv_name = discovery_info.get('name')
        model = discovery_info.get('model_name')
        host = discovery_info.get('host')
        name = "{} ({})".format(tv_name, model)
        port = DEFAULT_PORT
        timeout = DEFAULT_TIMEOUT
        mac = None
    else:
        _LOGGER.warning("Cannot determine device")
        return

    # Only add a device once, so discovered devices do not override manual
    # config.
    ip_addr = socket.gethostbyname(host)
    if ip_addr not in known_devices:
        known_devices.add(ip_addr)
        add_devices([SamsungTVDevice(host, port, name, timeout, mac)])
        _LOGGER.info("Samsung TV %s:%d added as '%s'", host, port, name)
    else:
        _LOGGER.info("Ignoring duplicate Samsung TV %s:%d", host, port)


class SamsungTVDevice(MediaPlayerDevice):
    """Representation of a Samsung TV."""

    def __init__(self, host, port, name, timeout, mac):
        """Initialize the Samsung device."""
        from wakeonlan import wol
        # Save a reference to the imported classes
        self._name = name
        self._mac = mac
        self._wol = wol
        # Assume that the TV is not muted
        self._muted = False
        self._volume = 0
        self._state = STATE_OFF
        # Generate a configuration for the Samsung library
        self._config = {
            'name': 'HomeAssistant',
            'description': name,
            'id': 'ha.component.samsung',
            'port': 7676,
            'host': host,
            'timeout': timeout,
        }
        self._selected_source = ''
        self._source_ids = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetSourceList', '', 'id')
        if self._source_ids:
            del self._source_ids[0]
            self._source_names = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetSourceList', '', 'sourcetype')
            self._sources = dict(zip(self._source_names, self._source_ids))
        else:
            self._source_names = {}
            self._source_ids = {}
            self._sources = {}

    def update(self):
        """Retrieve the latest data."""
        currentvolume = self.SendSOAP('smp_17_', 'urn:schemas-upnp-org:service:RenderingControl:1', 'GetVolume', '<InstanceID>0</InstanceID><Channel>Master</Channel>','currentvolume')
        if currentvolume:
            self._volume = int(currentvolume) / 100
            currentmute = self.SendSOAP('smp_17_', 'urn:schemas-upnp-org:service:RenderingControl:1', 'GetMute', '<InstanceID>0</InstanceID><Channel>Master</Channel>','currentmute')
            if currentmute == '1':
                self._muted = True
            else:
                self._muted = False
            source = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetCurrentExternalSource', '','currentexternalsource')
            self._selected_source = source
            self._state = STATE_ON
            return True
        else:
            self._state = STATE_OFF
            return False

    def SendSOAP(self,path,urn,service,body,XMLTag):
        CRLF = "\r\n"
        xmlBody = "";
        xmlBody += '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        xmlBody += '<s:Body>'
        xmlBody += '<u:{service} xmlns:u="{urn}">{body}</u:{service}>'
        xmlBody += '</s:Body>'
        xmlBody += '</s:Envelope>'
        xmlBody = xmlBody.format(urn = urn, service = service, body = body)

        soapRequest  = "POST /{path} HTTP/1.0%s" % (CRLF)
        soapRequest += "HOST: {host}:{port}%s" % (CRLF)
        soapRequest += "CONTENT-TYPE: text/xml;charset=\"utf-8\"%s" % (CRLF)
        soapRequest += "SOAPACTION: \"{urn}#{service}\"%s" % (CRLF)
        soapRequest += "%s" % (CRLF)
        soapRequest += "{xml}%s" % (CRLF)
        soapRequest = soapRequest.format(host = self._config['host'], port = self._config['port'], xml = xmlBody, path = path, urn = urn, service = service)


        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(0.5)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dataBuffer = ''
        response_xml = ''
        _LOGGER.info("Samsung TV sending: %s", soapRequest)

        try:
            client.connect( (self._config['host'], self._config['port']) )
            client.send(bytes(soapRequest, 'utf-8'))
            while True:
                dataBuffer = client.recv(4096)
                if not dataBuffer: break
                response_xml += str(dataBuffer)
        except socket.error as e:
            return

        response_xml = bytes(response_xml, 'utf-8')
        response_xml = response_xml.decode(encoding="utf-8")
        response_xml = response_xml.replace("&lt;","<")
        response_xml = response_xml.replace("&gt;",">")
        response_xml = response_xml.replace("&quot;","\"")
        _LOGGER.info("Samsung TV received: %s", response_xml)
        if XMLTag:
            soup = BeautifulSoup(str(response_xml), 'html.parser')
            xmlValues = soup.find_all(XMLTag)
            xmlValues_names = [xmlValue.string for xmlValue in xmlValues]
            if len(xmlValues_names)== 1:
                return xmlValues_names[0]
            else:
                return xmlValues_names
        else:
            return response_xml[response_xml.find('<s:Envelope'):]

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted
    @property

    def source(self):
        """Return the current input source."""
        return self._selected_source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_names

    @property
    def media_title(self):
        """Title of current playing media."""
        return self._selected_source

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        if self._mac:
            return SUPPORT_SAMSUNGTV | SUPPORT_TURN_ON
        return SUPPORT_SAMSUNGTV

    def select_source(self, source):
        """Select input source."""
        self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'SetMainTVSource', '<Source>'+source+'</Source><ID>' + self._sources[source] + '</ID><UiID>0</UiID>','')

    def turn_off(self):
        """Turn off media player."""

    def set_volume_level(self, volume):
        """Volume up the media player."""
        volset = str(round(volume * 100))
        self.SendSOAP('smp_17_', 'urn:schemas-upnp-org:service:RenderingControl:1', 'SetVolume', '<InstanceID>0</InstanceID><DesiredVolume>' + volset + '</DesiredVolume><Channel>Master</Channel>','')

    def volume_up(self):
        """Volume up the media player."""
        volume = self._volume + 0.01
        self.set_volume_level(volume)

    def volume_down(self):
        """Volume down media player."""
        volume = self._volume - 0.01
        self.set_volume_level(volume)

    def mute_volume(self, mute):
        """Send mute command."""
        if self._muted == True:
            doMute = '0'
        else:
            doMute = '1'
        self.SendSOAP('smp_17_', 'urn:schemas-upnp-org:service:RenderingControl:1', 'SetMute', '<InstanceID>0</InstanceID><DesiredMute>' + doMute + '</DesiredMute><Channel>Master</Channel>','')

    def turn_on(self):
        """Turn the media player on."""
        if self._mac:
            self._wol.send_magic_packet(self._mac)
