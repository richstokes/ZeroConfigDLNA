# ZeroConfigDLNA

Simple, cross-platform DLNA media server.  

Share media from your computer to your TV (or any other UPnP device!) with a single command. Runs on Windows, Linux, and MacOS.  

&nbsp;

## Quick Start - Windows
Windows users can [download the latest release here](https://github.com/richstokes/ZeroConfigDLNA/releases). Copy the .exe to the directory you wish to serve files from and double click to launch (you may need to accept the generic Windows security warning).

&nbsp;

## Quick Start - Mac & Linux

1. Clone or download this repository.
2. Run the application:
   ```bash
   python app.py
   ```
   This will serve media from the current directory by default.

3. To serve media from a different directory, use the `-d` flag:
   ```bash
   python app.py -d /path/to/your/media
   ```

This project uses only Python (3.4+) standard library features, so no additional packages or setup are required.

&nbsp;


## Install as a Linux Service
Great for if you have a dedicated media server. You can install ZeroConfigDLNA as a systemd service by running this one-liner interactive [install script](https://github.com/richstokes/ZeroConfigDLNA/blob/main/linux_install.sh). It will prompt you for the directory you wish to serve media from:
```bash
curl -fsSL https://raw.githubusercontent.com/richstokes/ZeroConfigDLNA/refs/heads/main/linux_install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh && rm /tmp/install.sh
```

The service will then auto-start on boot.  

To upgrade or change the media directory, simply re-run the install script command above.  

&nbsp;

## Why?

I wanted something quick and easy that would let me share videos from my laptop to my TV. The DLNA/media server implementations I tried seemed to be extremely over-complicated, needed tons of configuration, or were heavyweight with various other features bolted on.

By contrast, `ZeroConfigDLNA` has nothing to configure. You simply run it and it appears as a media server on your TV.


## Compatibility

Tested and known working on:  
- Sony Bravia Smart TV
- Samsung Smart TV
- Xbox Media Player
- VLC Media Player (including iPhone/iPad)  


Feel free to open an issue with the log output if you run into problems and I'll see if I can fix it. Use the `-v` flag to turn on verbose logging.  

