# home-assistant-samsungtv
A samsungtv.py fork to work with Samsung H6400

<img src="https://i.ibb.co/zZQMHCK/samsung.jpg">

This code is based on a post of MrUart232 @ home-assistant community<br />
https://community.home-assistant.io/t/control-newer-samsung-tvs/29895

I've fixed an issue with the source list to make it compatible with the api calls to my H6400 TV
I've been also trying to improve this as a media source with some additions

**Disclaimer:** I'm no python programmer by far. My code might be crude but i will try to make it as optimized as i can

### Installation
- Put samsungtv.py inside *{homeassistantconfigfolder}*/custom_components/media_player/ (create the folder structure if it not exists)
- Edit the configuration.yaml accordingly:
```
media_player:
  - platform: samsungtv
    host: 10.0.0.5
    usegoogle: True # Use google to auto-search for media image
````    

### Some research sources
- [upnp - control Samsung TV](https://forum.iobroker.net/viewtopic.php?t=4449)
- [Samsung-TV-Hacks](https://github.com/ohjeongwook/Samsung-TV-Hacks/blob/master/Servers/smp4.py)
- [Samsung Smart TV APIs and more](https://github.com/casperboone/homey-samsung-smart-tv/blob/master/samsung.md)
- [samsung smart tv channel switcher](https://github.com/yath/sstcs/)
### Future plans:
- [x] Get current playing channel
- [x] Retrieve channel list
- [x] Support media image w/ google image search
- [ ] Make it so you can change the media/channel (if possible)
