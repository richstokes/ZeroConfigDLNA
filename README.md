# ZeroConfigDLNA

Share media from your computer to your TV (or any other UPnP device!) with a single command.

## Quick Start

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


## Why?

I wanted something quick and easy that would let me share videos from my laptop to my TV. The DLNA/media server implementations I tried seemed to be extremely over-complicated, needed tons of configuration, or were heavyweight with various other features bolted on.

By contrast, `ZeroConfigDLNA` has nothing to configure. You simply run it and it appears as a media server on your TV.


## Compatibility

So far I've tested this on my Sony and Samsung TV's. It works great on both!

Feel free to open an issue with the log output if you run into problems and I'll see if I can fix it.

## How It Works

Curious about the technical details? Check out the [How It Works](how_it_works.md) documentation for a deep dive into DLNA, SSDP, and how this server is implemented.