"""
Support for interface with an Samsung TV.

For moee details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.samsungtv/
"""
import logging
import socket

REQUIREMENTS = ['wakeonlan==0.2.2', 'beautifulsoup4==4.6.0', 'requests==2.21.0', 'google-images-download==2.5.0']

from bs4 import BeautifulSoup

import voluptuous as vol
import re
import requests
from struct import unpack


from homeassistant.components.media_player import (
    SUPPORT_SELECT_SOURCE, SUPPORT_TURN_OFF, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP, MediaPlayerDevice, PLATFORM_SCHEMA, SUPPORT_TURN_ON)
from homeassistant.const import (
    CONF_HOST, CONF_NAME, STATE_OFF, STATE_ON, STATE_UNKNOWN, CONF_PORT,
    CONF_MAC)
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_TIMEOUT = 'timeout'
CONF_USEGOOGLE = 'usegoogle'

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

    _googleImage = config.get(CONF_USEGOOGLE)

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
        add_devices([SamsungTVDevice(host, port, name, timeout, mac, _googleImage)])
        _LOGGER.info("Samsung TV %s:%d added as '%s'", host, port, name)
    else:
        _LOGGER.info("Ignoring duplicate Samsung TV %s:%d", host, port)


class SamsungTVDevice(MediaPlayerDevice):
    """Representation of a Samsung TV."""

    def __init__(self, host, port, name, timeout, mac, googleImage):
        """Initialize the Samsung device."""
        from wakeonlan import wol
        from google_images_download import google_images_download

        if googleImage:
            self._googleImage = google_images_download.googleimagesdownload()
            self._programImages = {}
        else:
            self._googleImage = None

        # Save a reference to the imported classes
        self._name = name
        self._mac = mac
        self._wol = wol
        self._updateCounter = 60
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
        self._currentChannel = None
        self._channelsProgram = {}
        self._channels = {}
        self._source_ids = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetSourceList', '', 'id')
        if self._source_ids:
            del self._source_ids[0]
            self._source_names = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetSourceList', '', 'sourcetype')
            self._sources = dict(zip(self._source_names, self._source_ids))
            self.getChannelList()
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
            self._updateCounter += 1
            if self._updateCounter > 10:
                self.getChannelListProgram()
                self._updateCounter = 0
            if source == 'TV':
                self.getCurrentChannel()
            return True
        else:
            self._state = STATE_OFF
            self._updateCounter = 0
            return False

    def SendSOAP(self,path,urn,service,body,XMLTag, regexMatch=False):
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
#        _LOGGER.info("Samsung TV sending: %s", soapRequest)

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
#        _LOGGER.info("Samsung TV received: %s", response_xml)
        if regexMatch:
            _ma = re.search('.*<'+XMLTag+'>(.*?)</'+XMLTag+'>.*',response_xml)
            if _ma is not None:
                return _ma.group(1)
            else:
                return ''
        elif XMLTag:
            soup = BeautifulSoup(str(response_xml), 'html.parser')
            xmlValues = soup.find_all(XMLTag)
#            _LOGGER.info('SOMETHING: %s',xmlValues)
            xmlValues_names = [xmlValue.string for xmlValue in xmlValues]
            if len(xmlValues_names)== 1:
                return xmlValues_names[0]
            else:
                return xmlValues_names
        else:
            return response_xml[response_xml.find('<s:Envelope'):]

    def findTag(self, soup, tag):
        xmlValues = soup.find_all(tag)
        xmlValues_names = [xmlValue.string for xmlValue in xmlValues]
        if len(xmlValues_names)== 1:
            return xmlValues_names[0]
        else:
            return xmlValues_names

    def getChannelList(self):
#        _LOGGER.info('getting channel list')
        _uri = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetChannelListURL', '','channellisturl')
#        _LOGGER.info('got uri: %s',_uri)
        if _uri is not None:
            r = requests.get(_uri)
        self._parse_channel_list(r.content)

    def _getint(self, buf, offset):
        """Helper function to extract a 16-bit little-endian unsigned from a char
        buffer 'buf' at offset 'offset'..'offset'+2."""
        x = unpack('<H', buf[offset:offset+2])
        return x[0]

    def getChannelListProgram(self):
        _LOGGER.info('getting channel list')
        _uri = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetCurrentProgramInformationURL', '','currentproginfourl')
#        _LOGGER.info('got uri: %s',_uri)
        if _uri is not None:
            r = requests.get(_uri)
#            _content = bytes(r.content, 'utf-8')
            _content = r.content.decode(encoding="utf-8")
            _program = BeautifulSoup(_content, 'html.parser')
            _channelIDs = self.findTag(_program, 'majorch')
            _mediaTitles = self.findTag(_program, 'title')
            self._channelsProgram = {}
            for i in range(len(_channelIDs)):
                self._channelsProgram[_channelIDs[i]]= {'title': _mediaTitles[i]}
            return self._channelsProgram
        else:
            return {}


    def getCurrentChannel(self):
        _ch = self.SendSOAP('smp_4_', 'urn:samsung.com:service:MainTVAgent2:1', 'GetCurrentMainTVChannel', '','majorch')
        if _ch in self._channels:
            self._currentChannel = self._channels[_ch]
#            _LOGGER.info('CurrentChannel: %s',self._currentChannel)
        else:
            self._currentChannel = None
#            _LOGGER.info('Channel %s not found in channel list. Using %s',_ch,self._currentChannel)

    def _parse_channel_list(self, channel_list):
        """Splits the binary channel list into channel entry fields and returns a list of Channels."""

        # The channel list is binary file with a 4-byte header, containing 2 unknown bytes and
        # 2 bytes for the channel count, which must be len(list)-4/124, as each following channel
        # is 124 bytes each. See Channel._parse_dat for how each entry is constructed.

        if len(channel_list) < 128:
            _LOGGER.info('channel list is smaller than it has to be for at least one channel (%d bytes (actual) vs. 128 bytes',len(channel_list))

        if (len(channel_list)-4) % 124 != 0:
            _LOGGER.info('channel list\'s size (%d) minus 128 (header) is not a multiple of 124 bytes',len(channel_list))

        actual_channel_list_len = (len(channel_list)-4) / 124
        expected_channel_list_len = self._getint(channel_list, 2)
        if actual_channel_list_len != expected_channel_list_len:
            _LOGGER.info('Actual channel list length ((%d-4)/124=%d) does not equal expected channel list length (%d) as defined in header',len(channel_list),actual_channel_list_len, expected_channel_list_len)

        self._channels = {}
        pos = 4
        while pos < len(channel_list):
            chunk = channel_list[pos:pos+124]
            _channel = Channel(chunk)
            self._channels['{}'.format(_channel.major_ch)] = _channel
            pos += 124
        return self._channels

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
        if self._currentChannel is not None:
            return self._currentChannel.title+' - '+self.current_playing_program
        else:
            return 'Unknown'

    @property
    def current_playing_program(self):
        _ch = '{}'.format(self._currentChannel.major_ch)
        if _ch in self._channelsProgram:
            return str(self._channelsProgram[_ch]['title'])
        else:
            return 'Unknown'

    @property
    def media_image_url(self):
        """Return the media image URL."""
        if self._googleImage is None:
            return None
        if self.current_playing_program == 'Unknown':
            return None
        if self.current_playing_program in self._programImages:
            return self._programImages[self.current_playing_program]
        else:
            arguments = {"keywords":self.current_playing_program,"limit":1,"print_urls":True,"no_download":True,"language":False,
                         "time_range":False,"exact_size":False,"color":None,"color_type":None,"usage_rights":None,"size":">800*600",
                         "type":None,"time":None,"aspect_ratio":"wide","format":None,"offset":False,"metadata":False,
                         "socket_timeout":False,"prefix":False,"print_size":False,"print_paths":False,"extract_metadata":False,
                         "no_numbering":False,"thumbnail":False,"delay":False}
            _gparams = self._googleImage.build_url_parameters(arguments)
            _gurl = self._googleImage.build_search_url(arguments["keywords"],_gparams,None,None,None,None)
            _html = self._googleImage.download_page(_gurl)
            _items,_errorCount,_abs_path = self._googleImage._get_all_items(_html,"","",arguments["limit"],arguments)
            if len(_items)>0:
               self._programImages[self.current_playing_program] = _items[0]['image_link']
               return _items[0]['image_link']
            else:
               return ''
#        return "https://image.shutterstock.com/z/stock-vector-television-with-an-inscription-tv-program-logo-design-vector-illustration-708238828.jpg"

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



class Channel(object):
    """Class representing a Channel from the TV's channel list."""

    def __init__(self, from_dat):
        """Constructs the Channel object from a binary channel list chunk."""
        self._parse_dat(from_dat)

    def _parse_dat(self, buf):
        """Parses the binary data from a channel list chunk and initilizes the
        member variables."""

        # Each entry consists of (all integers are 16-bit little-endian unsigned):
        #   [2 bytes int] Type of the channel. I've only seen 3 and 4, meaning
        #                 CDTV (Cable Digital TV, I guess) or CATV (Cable Analog
        #                 TV) respectively as argument for <ChType>
        #   [2 bytes int] Major channel (<MajorCh>)
        #   [2 bytes int] Minor channel (<MinorCh>)
        #   [2 bytes int] PTC (Physical Transmission Channel?), <PTC>
        #   [2 bytes int] Program Number (in the mux'ed MPEG or so?), <ProgNum>
        #   [2 bytes int] They've always been 0xffff for me, so I'm just assuming
        #                 they have to be :)
        #   [4 bytes string, \0-padded] The (usually 3-digit, for me) channel number
        #                               that's displayed (and which you can enter), in ASCII
        #   [2 bytes int] Length of the channel title
        #   [106 bytes string, \0-padded] The channel title, in UTF-8 (wow)

        t = self._getint(buf, 0)
        if t == 4:
            self.ch_type = 'CDTV'
        elif t == 3:
            self.ch_type = 'CATV'
        elif t == 2:
            self.ch_type = 'DTV'
        else:
            _LOGGER.info('Unknown channel type %d', t)

        self.major_ch = self._getint(buf, 2)
        self.minor_ch = self._getint(buf, 4)
        self.ptc      = self._getint(buf, 6)
        self.prog_num = self._getint(buf, 8)

        if self._getint(buf, 10) != 0xffff:
            _LOGGER.info('reserved field mismatch (%04x)', self._getint(buf, 10))

        self.dispno = buf[12:16].decode('utf-8').rstrip('\x00')
        title_len = self._getint(buf, 22)
        self.title = buf[24:24+title_len].decode('utf-8')

    def _getint(self, buf, offset):
        """Helper function to extract a 16-bit little-endian unsigned from a char
        buffer 'buf' at offset 'offset'..'offset'+2."""
        x = unpack('<H', buf[offset:offset+2])
        return x[0]

    def display_string(self):
        """Returns a unicode display string, since both __repr__ and __str__ convert it
        to ascii."""

        return u'[%s] % 4s %s' % (self.ch_type, self.dispno, self.title)

    def __repr__(self):
        return '<Channel %s %s ChType=%s MajorCh=%d MinorCh=%d PTC=%d ProgNum=%d>' % \
            (self.dispno, repr(self.title), self.ch_type, self.major_ch, self.minor_ch, self.ptc,
             self.prog_num)

    @property
    def as_xml(self):
        """The channel list as XML representation for SetMainTVChannel."""

        return ('<?xml version="1.0" encoding="UTF-8" ?><Channel><ChType>%s</ChType><MajorCh>%d'
                '</MajorCh><MinorCh>%d</MinorCh><PTC>%d</PTC><ProgNum>%d</ProgNum></Channel>') % \
            (escape(self.ch_type), self.major_ch, self.minor_ch, self.ptc, self.prog_num)
