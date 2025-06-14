# ZeroConfigDLNA
Run one command, serve media to your TV

`python app.py`  

Or, if you want to serve files from another directory: `python app.py -d ~/Downloads`  

This project uses features from the Python standard library. No other packages/setup is required to run.  


&nbsp;


### Why?
I wanted something quick and easy that would let me share videos from my laptop to my TV. Most DLNA/media server implementations I tried seemed to be extremely over-complicated, needed tons of configuration, or were heavyweight with various other features bolted on.  

By contrast, `ZeroConfigDLNA` has nothing to configure. You simply run it and it appears as a media server on your TV.  


### Compatability
So far I've tested this on my Sony TV. It works! Feel free to open an issue with the log output if you run into problems and I'll see if I can fix it. 