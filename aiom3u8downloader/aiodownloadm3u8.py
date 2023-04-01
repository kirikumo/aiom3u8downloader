#!/usr/bin/env python3
# coding=utf-8
"""download m3u8 file reliably.

Features:
- support HTTP and HTTPS proxy
- support retry on error/connect lost
- convert ts files to final mp4 file

"""

from __future__ import print_function, unicode_literals

import argparse
import asyncio
import logging
import os
import os.path
import re
import signal
import subprocess
import sys
from collections import OrderedDict
from tempfile import gettempdir
from urllib.parse import urljoin, urlparse

import aiohttp
import requests

import aiom3u8downloader
from aiom3u8downloader.configlogger import load_logger_config

IMG_SUFFIX_LIST = ['.png', '.jpg', '.jpeg', '.bmp']


def get_local_file_for_url(tempdir, url, path_line=None):
    """get absolute local file path for given url.

    Args:
        tempdir: temp dir to store downloaded files.
        url: resource url. includes protocol, host, path.
        path_line: optional, the path as it appears in the m3u8 file.
                   could be http relative path, local file path etc.

    """
    if path_line and path_line.startswith(tempdir):
        # avoid rewrite m3u8 path if it has already been rewritten in previous
        # runs.
        return keep_ts_suffix(path_line)
    path = keep_ts_suffix(get_url_path(url))
    repath = windows_safe_filename_without_path(path)
    if repath.startswith("/"):
        repath = repath[1:]
    return os.path.normpath(os.path.join(tempdir, repath))


def is_higher_resolution(new_resolution, old_resolution):
    """return True if new_resolution is higher than old_resolution.

    if old_resolution is None, just return True.

    resolution should be "1920x1080" format string.

    """
    if not old_resolution:
        return True
    return int(new_resolution.split("x")[0]) > int(
        old_resolution.split("x")[0])


def filesizeMiB(filename):
    s = os.stat(filename)
    return s.st_size / 1024 / 1024.0


def get_url_path(url):
    """get path part for a url.

    """
    return urlparse(url).path


def ensure_dir_exists_for(full_filename):
    """create file's parent dir if it doesn't exist.

    """
    os.makedirs(os.path.dirname(full_filename), exist_ok=True)


def get_basename(filename):
    """return filename with path and ext removed.

    """
    return os.path.splitext(os.path.basename(filename))[0]


def get_fullpath(filename):
    """make a canonical absolute path filename.

    """
    return os.path.abspath(os.path.expandvars(os.path.expanduser(filename)))


def keep_ts_suffix(path: str):
    for img_suffix in IMG_SUFFIX_LIST:
        if not path.lower().endswith(img_suffix):
            continue
        tsPath = path[:-len(img_suffix)] + '.ts'
        return tsPath
    return path


def rewrite_key_uri(tempdir, m3u8_url, key_line):
    """rewrite key URI in given '#EXT-X-KEY:' line.

    Args:
        tempdir: temp download dir.
        m3u8_url: playlist url.
        key_line: the line in m3u8 file that contains an encrypt key.

    Return:
        a new line with URI rewritten to local path.

    """
    pattern = re.compile(r'^(.*URI=")([^"]+)(".*)$')
    mo = pattern.match(key_line)
    if not mo:
        raise RuntimeError("key line doesn't have URI")
    prefix = mo.group(1)
    uri = mo.group(2)
    suffix = mo.group(3)

    if uri and uri.startswith(tempdir):
        # already using local file path in uri.
        return keep_ts_suffix(key_line)

    url = urljoin(m3u8_url, uri)
    local_key_file = get_local_file_for_url(tempdir, url, key_line)
    if re.match('^.:\\\\', local_key_file):
        # in windows, backward slash won't work in key URI. ffmpeg doesn't
        # accept backward slash.
        local_key_file = local_key_file.replace('\\', '/')
    return keep_ts_suffix(prefix + local_key_file + suffix)


def windows_safe_filename_without_path(name):
    # see
    # https://docs.microsoft.com/en-us/windows/desktop/fileio/naming-a-file
    replace_chars = {
        '<': '《',
        '>': '》',
        ':': '：',
        '"': '“',
        '|': '_',
        '?': '？',
        '*': '_',
    }
    for k, v in replace_chars.items():
        name = name.replace(k, v)
    return name

def _windows_safe_filename(name):
    # see
    # https://docs.microsoft.com/en-us/windows/desktop/fileio/naming-a-file
    replace_chars = {
        '<': '《',
        '>': '》',
        ':': '：',
        '"': '“',
        '/': '_',
        '\\': '_',
        '|': '_',
        '?': '？',
        '*': '_',
    }
    for k, v in replace_chars.items():
        name = name.replace(k, v)
    return name


def safe_file_name(name):
    """replace special characters in name so it can be used as file/dir name.

    Args:
        name: the string that will be used as file/dir name.

    Return:
        a string that is similar to original string and can be used as
        file/dir name.

    """
    if sys.platform == 'win32':
        name = _windows_safe_filename(name)
    else:
        replace_chars = {
            '/': '_',
        }
        for k, v in replace_chars.items():
            name = name.replace(k, v)
    return name


def write_file(file_path, content):
    with open(file_path, 'wb') as f:
        f.write(content)


class ContentIsNoneError(Exception): ...

class AioM3u8Downloader:

    def __init__(
            self,
            url,
            output_filename,
            tempdir=".",
            limit_conn=100,
            auto_rename=False,
            logger: logging.Logger = logging.getLogger(),
    ):
        self.start_url = url

        # make sure output_filename is a safe filename on platform.
        # mainly for windows.
        safe_output_filename = os.path.join(
            os.path.dirname(output_filename),
            safe_file_name(os.path.basename(output_filename)))

        if safe_output_filename != output_filename:
            output_filename = safe_output_filename
            logger.warning("using modified output_filename=%s",
                           output_filename)
        else:
            logger.debug("output_filename=%s", output_filename)
        self.output_filename = get_fullpath(output_filename)
        self.tempdir = get_fullpath(
            os.path.join(tempdir, get_basename(output_filename)))
        try:
            os.makedirs(self.tempdir, exist_ok=True)
            logger.debug("using temp dir at: %s", self.tempdir)
        except IOError as _:
            logger.exception("create tempdir failed for: %s", self.tempdir)
            raise

        self.media_playlist_localfile = None
        self.limit_conn = limit_conn
        self.auto_rename = auto_rename
        self.total_fragments = 0
        # {full_url: local_file}
        self.fragments = OrderedDict()
        self.session = None
        self.logger = logger

    async def aio_get_url_content(self, url):
        """async fetch url, return content as bytes.

        """
        interval = [1, 5, 10]
        for sec in interval:
            try:
                self.logger.debug("GET %s", url)
                async with self.session.get(url) as response:
                    if not response.ok:
                        raise requests.HTTPError(response)
                    return await response.read()
            except Exception as e:
                await asyncio.sleep(sec)
        self.logger.exception(f"fragment download failed: {url}")

    def rewrite_http_link_in_m3u8_file(self, local_m3u8_filename, m3u8_url):
        """rewrite fragment url to local relative file path.

        """
        with open(local_m3u8_filename, 'r') as f:
            content = f.read()
        with open(local_m3u8_filename, 'w') as f:
            for line in content.split('\n'):
                if line.startswith('#'):
                    if line.startswith('#EXT-X-KEY:'):
                        f.write(rewrite_key_uri(self.tempdir, m3u8_url, line))
                    else:
                        f.write(line)
                    f.write('\n')
                elif line.strip() == '':
                    f.write(line)
                    f.write('\n')
                else:
                    f.write(
                        get_local_file_for_url(self.tempdir,
                                               urljoin(m3u8_url, line), line))
                    f.write('\n')
        self.logger.info("http links rewrote in m3u8 file: %s",
                         local_m3u8_filename)

    def remake_path(self, target_mp4_path):
        folder_path = os.path.dirname(target_mp4_path)
        file_name_list = os.listdir(folder_path)
        file_name = os.path.basename(target_mp4_path)
        if file_name in file_name_list:
            self.logger.info(f'File "{file_name}" already exists')
            r = re.compile(f'({file_name[:-4]}|{file_name[:-4]}_[1-9]*)\.mp4')
            name_count = len(list(filter(r.match, file_name_list)))
            remake_path = f'{target_mp4_path[:-4]}_{name_count}.mp4'
            self.logger.info(f'Rename to "{remake_path}"')
            return remake_path
        return target_mp4_path

    def start(self):
        loop = asyncio.get_event_loop()
        success = loop.run_until_complete(
            asyncio.ensure_future(self.aio_download_m3u8_link(self.start_url)))

        if not success:
            return None, False

        target_mp4 = self.output_filename
        if not target_mp4.endswith(".mp4"):
            target_mp4 += ".mp4"

        ensure_dir_exists_for(target_mp4)
        if self.auto_rename:
            target_mp4 = self.remake_path(target_mp4)

        cmd = [
            "ffmpeg", "-nostdin", "-loglevel", "warning",
            "-allowed_extensions", "ALL", "-i", self.media_playlist_localfile,
            "-acodec", "copy", "-vcodec", "copy", "-bsf:a", "aac_adtstoasc",
            target_mp4
        ]
        self.logger.info("Running: %s", cmd)
        proc = subprocess.run(cmd)

        if proc.returncode != 0:
            self.logger.error('---------------------------------------------')
            self.logger.error(
                f"run ffmpeg command failed: exitcode={proc.returncode}")
            if proc.stderr:
                self.logger.error('=> ' + proc.stderr.decode('utf-8'))
            self.logger.error('---------------------------------------------')
            sys.exit(proc.returncode)

        self.logger.info("mp4 file created, size=%.1fMiB, filename=%s",
                         filesizeMiB(target_mp4), target_mp4)
        self.logger.info("Removing temp files in dir: \"%s\"", self.tempdir)
        if os.path.exists("/bin/rm"):
            subprocess.run(["/bin/rm", "-rf", self.tempdir])
        elif os.path.exists("C:/Windows/SysWOW64/cmd.exe"):
            subprocess.run(["rd", "/s", "/q", self.tempdir], shell=True)
        self.logger.info("temp files removed")

        return target_mp4, True

    async def aio_mirror_url_resource(self, remote_file_url: str):
        """ return fragment_full_name, reuse, success """
        local_file = get_local_file_for_url(self.tempdir, remote_file_url)
        if os.path.exists(local_file):
            self.logger.debug("skip downloaded resource: %s", remote_file_url)
            return local_file, True, True
        content = await self.aio_get_url_content(remote_file_url)
        if content is None:
            return None, False, False

        ensure_dir_exists_for(local_file)
        if any(map(remote_file_url.lower().endswith, IMG_SUFFIX_LIST)):
            # image to ts
            content = content[212:]

        write_file(local_file, content)
        return local_file, False, True

    async def aio_download_key(self, url, key_line):
        """download key.

        This will replicate key file in local dir.

        Args:
            key_line: a line looks like #EXT-X-KEY:METHOD=AES-128,URI="key.key"

        """
        pattern = re.compile(r'URI="([^"]+)"')
        mo = pattern.search(key_line)
        if not mo:
            raise RuntimeError("key line doesn't have URI")
        uri = mo.group(1)
        key_url = urljoin(url, uri)
        local_key_file, reuse, success = await self.aio_download_fragment(key_url)
        if reuse:
            self.logger.debug("reuse key at: %s", local_key_file)
        else:
            self.logger.debug("key downloaded at: %s", local_key_file)
        return success

    async def aio_download_fragment(self, url):
        """download a video fragment.

        """
        fragment_full_name, reuse, success = await self.aio_mirror_url_resource(url)
        if fragment_full_name:
            if reuse:
                self.logger.debug(f"reuse fragment at: {fragment_full_name}", )
            else:
                self.logger.debug(f"fragment created at: {fragment_full_name}")
        return (url, fragment_full_name, success)

    def fragment_downloaded_from_future(self, future):
        """apply_async callback.

        """
        url, fragment_full_name, success = future.result()
        if not success: return
        self.fragments[url] = fragment_full_name
        # progress log
        fetched_fragment = len(self.fragments)
        if fetched_fragment == self.total_fragments:
            self.logger.info("100%%, %s fragments fetched",
                             self.total_fragments)
        elif fetched_fragment % 10 == 0:
            self.logger.info("[%2.0f%%] %3s/%s fragments fetched",
                             fetched_fragment * 100.0 / self.total_fragments,
                             fetched_fragment, self.total_fragments)

    async def aio_download_fragments(self, fragment_urls):
        self.total_fragments = len(fragment_urls)
        self.logger.info("playlist has %s fragments", self.total_fragments)

        tasks = []
        for url in fragment_urls:
            if url in self.fragments:
                self.logger.info("skip downloaded fragment: %s", url)
                continue
            task = asyncio.ensure_future(self.aio_download_fragment(url=url))
            task.add_done_callback(self.fragment_downloaded_from_future)
            tasks.append(task)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        statusList = [success for _,_,success in results]
        if statusList.count(False) > len(tasks) * 0.05:
            return False
        return True

    async def aio_process_media_playlist(self, url, content=None):
        """replicate every file on the playlist in local temp dir.

        Args:
            url: media playlist url
            content: the playlist content for resource at the url.

        """
        self.media_playlist_localfile, _, _success = await self.aio_mirror_url_resource(
            url)
        if not _success:
            return False

        # always try rewrite because we can't be sure whether the copy in
        # cache dir has been rewritten yet.
        self.rewrite_http_link_in_m3u8_file(self.media_playlist_localfile, url)
        if content is None:
            content = await self.aio_get_url_content(url)

            if content is None:
                return False

        fragment_urls = []
        for line in content.decode("utf-8").split('\n'):
            if line.startswith('#EXT-X-KEY'):
                success = await self.aio_download_key(url, line)
                if not success: return False
                continue
            if line.startswith('#') or line.strip() == '':
                continue
            if line.endswith(".m3u8"):
                self.logger.info("media playlist should not include .m3u8")
                # raise RuntimeError("media playlist should not include .m3u8")
                return False
            fragment_urls.append(urljoin(url, line))

        success = await self.aio_download_fragments(fragment_urls)
        self.logger.info("media playlist all fragments downloaded")
        
        return success

    async def aio_process_master_playlist(self, url, content):
        """choose the highest quality media playlist, and download it.

        """
        last_resolution = None
        target_media_playlist = None
        replace_on_next_line = False
        pattern = re.compile(r'RESOLUTION=([0-9]+x[0-9]+)')
        for line in content.decode("utf-8").split('\n'):
            mo = pattern.search(line)
            if mo:
                resolution = mo.group(1)
                if is_higher_resolution(resolution, last_resolution):
                    last_resolution = resolution
                    replace_on_next_line = True
            if line.startswith('#'):
                continue
            if replace_on_next_line:
                target_media_playlist = line
                replace_on_next_line = False
            if target_media_playlist is None:
                target_media_playlist = line
        self.logger.info("chose resolution=%s uri=%s", last_resolution,
                         target_media_playlist)
        success = await self.aio_process_media_playlist(
            urljoin(url, target_media_playlist))

        return success

    async def aio_download_m3u8_link(self, url):
        """download video at m3u8 link.

        """

        my_conn = aiohttp.TCPConnector(limit=self.limit_conn)
        async with aiohttp.ClientSession(connector=my_conn) as session:

            self.session = session

            content = await self.aio_get_url_content(url)
            if content is None:
                return False

            if "RESOLUTION" in content.decode('utf-8'):
                success = await self.aio_process_master_playlist(url, content)
            else:
                success = await self.aio_process_media_playlist(url, content)

        return success


def signal_handler(self, sig, frame):
    # Note: subprocess will auto exit when parent process exit.

    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(prog='aiom3u8downloader',
                                     description="download video at m3u8 url")
    parser.add_argument('--version',
                        action='version',
                        version='%(prog)s ' + aiom3u8downloader.__version__)
    parser.add_argument('--debug',
                        action='store_true',
                        help='enable debug log')
    parser.add_argument('--output',
                        '-o',
                        required=True,
                        help='output video filename, e.g. ~/Downloads/foo.mp4')
    parser.add_argument(
        '--tempdir',
        default=os.path.join(gettempdir(), 'aiom3u8downloader'),
        help='temp dir, used to store .ts files before combing them into mp4')
    parser.add_argument(
        '--limit_conn',
        '-conn',
        type=int,
        default=100,
        help='limit amount of simultaneously opened connections')
    parser.add_argument('url', metavar='URL', help='the m3u8 url')
    parser.add_argument(
        '--auto_rename',
        '-ar',
        action='store_true',
        help='auto rename when output file name already exists',
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("aiom3u8downloader").setLevel(logging.DEBUG)
        logging.debug("debug set to true")

    logger = logging.getLogger('aiom3u8downloader')
    logger.debug("setup signal_handler for SIGINT and SIGTERM")
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    downloader = AioM3u8Downloader(
        args.url,
        args.output,
        tempdir=args.tempdir,
        limit_conn=args.limit_conn,
        auto_rename=args.auto_rename,
        logger=logger,
    )
    downloader.start()


if __name__ == '__main__':
    logging.captureWarnings(True)
    load_logger_config()

    main()
