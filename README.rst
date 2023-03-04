aiom3u8downloader
============================

Update package m3u8downloader to use aiohttp to speed up download m3u8 url

Support disguised as img (png/jpg/jpeg) to decode into ts file

aiom3u8downloader base on package m3u8downloader (https://pypi.org/project/m3u8downloader, version: 0.10.1)

ffmpeg is used to convert the downloaded fragments into final mp4 video file.

.. _HTTP Live Streaming (HLS): https://developer.apple.com/streaming/

Installation
------------

To install aiom3u8downloader, simply:

.. code-block:: bash

   $ sudo apt install -y ffmpeg
   # python version >= python3.6
   $ pip install aiom3u8downloader

Quick Start
-----------

Example command line usage:

.. code-block:: bash

   aiodownloadm3u8 -o ~/Downloads/foo.mp4 https://example.com/path/to/foo.m3u8

If ~/.local/bin is not in $PATH, you can use full path:

.. code-block:: bash

   ~/.local/bin/aiodownloadm3u8 -o ~/Downloads/foo.mp4 https://example.com/path/to/foo.m3u8

Here is built-in command line help:

.. code-block:: text

   usage: aiom3u8downloader [-h] [--version] [--debug] --output OUTPUT
                              [--tempdir TEMPDIR] [--limit_conn LIMIT_CONN]
                              [--auto_rename] URL
   
   download video at m3u8 url
   
   positional arguments:
     URL                   the m3u8 url
   
   optional arguments:
     -h, --help                  show this help message and exit
     --version                   show program's version number and exit
     --debug                     enable debug log
     --output OUTPUT, -o OUTPUT
                                 output video filename, e.g. ~/Downloads/foo.mp4
     --tempdir TEMPDIR           temp dir, used to store .ts files before combing them into mp4
     --limit_conn LIMIT_CONN, -conn LIMIT_CONN
                                 limit amount of simultaneously opened connections
     --auto_rename, -ar          auto rename when output file name already exists

Limitations
-------------

This tool only parses minimum m3u8 extensions for selecting media playlist
from master playlist, downloading key and fragments from media playlist. If a
m3u8 file doesn't download correctly, it's probably some new extension was
added to the HLS spec which this tool isn't aware of.

ChangeLog
---------

* v0.0.1

  - use aiohttp download m3u8 url

* v1.0.3

  - remove multiprocessing package

  - release to pypi
