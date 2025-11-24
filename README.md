# aiom3u8downloader

aiom3u8downloader is a fast, reliable command-line HLS (m3u8) downloader and
MP4 assembler written in Python. It uses asynchronous HTTP requests (`aiohttp`)
to download media segments in parallel, supports robust retry logic, and
leverages `ffmpeg` to mux the downloaded fragments into a single MP4 file.

Designed for both servers and desktops (Linux/Windows/macOS), it is ideal for
users who want a lightweight tool to save HLS streams to local MP4 files.

This project is based on the `m3u8downloader` package (https://pypi.org/project/m3u8downloader),
originally released as version 0.10.1 — aiom3u8downloader started as an async
rewrite and enhancement of that project.

## Highlights / New Features

- Support for high-speed parallel downloads using `aiohttp` and `asyncio`.
- Handles media segments disguised as images (PNG/JPG/JPEG/BMP) and converts
  them into `.ts` fragments automatically.
- New: optional ad cutting via the `--cut_ads` flag which attempts to
  filter out ad segments before assembling the final MP4 (slows synthesis but
  produces cleaner videos).
- Auto-rename output file when a file with the same name already exists
  (`--auto_rename`).
- Cross-platform filename safety improvements for Windows paths.
- Configurable connection concurrency (`--limit_conn`) and robust retry
  behavior for flaky networks.

## Requirements

- Python 3.6+
- `ffmpeg` (install with your OS package manager: e.g. `sudo apt install ffmpeg`)
- Optional: for Windows, ensure `ffmpeg` is on your PATH

## Installation

```bash
# Install ffmpeg first (Linux example)
$ sudo apt install -y ffmpeg
# Install the Python package
$ pip install aiom3u8downloader
```

## Quick Start

Download an m3u8 and save as MP4:

```bash
$ aiodownloadm3u8 -o ~/Downloads/foo.mp4 https://example.com/path/to/foo.m3u8
```

### Common options

- `--output`, `-o` : output MP4 filename (required)
- `--tempdir`      : temporary directory for segment files (default under system
  temp)
- `--limit_conn`   : limit of concurrent connections (default: 100)
- `--auto_rename`  : append timestamp if the output file already exists
- `--cut_ads`      : try to filter out advertising segments before muxing
- `--debug`        : enable debug logging

If `~/.local/bin` is not in your PATH, run the installed script with its full
path (e.g. `~/.local/bin/aiodownloadm3u8 ...`).

## Usage (built-in help)

```
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
  --cut_ads, -c               attempt to filter out ad segments before combining
```

## Limitations

This tool implements the common m3u8/HLS features required to choose a media
playlist from a master playlist, download encryption keys and media segments,
and assemble them into an MP4 using `ffmpeg`. It does not implement every
extension of the HLS specification; if a playlist uses a newer or uncommon
extension this tool may fail to download correctly.

## ChangeLog

* v1.0.x

  - remove multiprocessing package
  - release to pypi

* v1.1.x

  - async rewrite using `aiohttp` for faster parallel downloads
  - support for segments disguised as images (png/jpg/jpeg/bmp)
  - added `--auto_rename` and Windows-safe filename handling

* v1.2.0

  - added `--cut_ads` option to attempt ad removal before muxing
