# ZeroConfigDLNA
Run one command, serve media to your TV!  

Clone/download this repo and run:  
`python app.py`  

(By default it will serve media from the current directory)

If you want to serve files from another directory, use the `-d` flag, e.g:  
`python app.py -d ~/Downloads`  


This project uses features from the Python standard library. No other packages/setup is required to run.  


&nbsp;


### Why?
I wanted something quick and easy that would let me share videos from my laptop to my TV. The DLNA/media server implementations I tried seemed to be extremely over-complicated, needed tons of configuration, or were heavyweight with various other features bolted on.  

By contrast, `ZeroConfigDLNA` has nothing to configure. You simply run it and it appears as a media server on your TV.  


### Compatability
So far I've tested this on my Sony TV. It works! Feel free to open an issue with the log output if you run into problems and I'll see if I can fix it. 

### How It Works
Curious about the technical details? Check out the [How It Works](how_it_works.md) documentation for a deep dive into DLNA, SSDP, and how this server is implemented.