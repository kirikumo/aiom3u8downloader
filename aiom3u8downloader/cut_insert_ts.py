import asyncio
import json
import logging
import subprocess
import traceback
from collections import defaultdict
from copy import deepcopy
from pathlib import Path


class CutInsertTs:
    def __init__(self, logger: logging.Logger = logging.getLogger()):
        self.logger = logger

    @staticmethod
    def _get_first_ts_path(lines):
        for line in lines:
            if not line:
                continue
            candidate = line.strip()
            if candidate.lower().endswith('.ts'):
                return candidate
        return None

    @staticmethod
    def _group_lines(m3u8_path):
        with Path(m3u8_path).open() as f:
            content = f.read()
        file_lines = content.split('\n')
        groups = []
        tmp_lines = []
        for line in file_lines:
            if line == '#EXT-X-DISCONTINUITY':
                groups.append(tmp_lines)
                tmp_lines = []
            if line == '#EXT-X-ENDLIST':
                groups.append(tmp_lines)
                tmp_lines = []
            tmp_lines.append(line)
        groups.append(tmp_lines)
        return groups

    @staticmethod
    def _get_top_line_info(
        ts_path,
        stream_tags='codec_type,width,height,r_frame_rate,sample_rate,start_pts',
    ):
        try:
            cmd = [
                'ffprobe',
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-read_intervals',
                '%+0.1',  # 只读取前0.1秒的数据
                '-select_streams',
                'v:0,a:0',  # 只获取第一个视频和音频流，加快速度
                '-show_entries',
                f'stream={stream_tags}',
                ts_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            info = {}
            streams = data.get('streams')
            if streams:
                stream = streams[0]
                # return ','.join([str(x) for x in stream.values()])
                # return stream
                if stream.get('codec_type') == 'video':
                    info['tag'] = (
                        f'{stream["width"]}x{stream["height"]},{stream.get("r_frame_rate", "")}'
                    )
                    # info['width'] = stream['width']
                    # info['height'] = stream['height']
                    # if 'r_frame_rate' in stream:
                    #     num, den = map(int, stream['r_frame_rate'].split('/'))
                    #     info['fps'] = str(round(num / den, 2)) if den != 0 else '0'
                elif stream.get('codec_type') == 'audio':
                    info['tag'] = str(stream.get('sample_rate'))
                info['pts'] = stream.get('start_pts', 0)

            return info

        except Exception:
            traceback.print_exc()

        return {}

    @staticmethod
    async def _async_get_top_line_info(
        ts_path,
        stream_tags='codec_type,width,height,sample_rate,start_pts,start_time',
    ):
        cmd = [
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-read_intervals',
            '%+0.1',
            '-select_streams',
            'v:0,a:0',
            '-show_entries',
            f'stream={stream_tags}',
            ts_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            data = json.loads(stdout.decode())

            streams = data.get('streams')
            if streams:
                info = {}
                stream = streams[0]
                if stream.get('codec_type') == 'video':
                    info['tag'] = f'{stream["width"]}x{stream["height"]}'

                elif stream.get('codec_type') == 'audio':
                    info['tag'] = str(stream.get('sample_rate'))
                info['pts'] = stream.get('start_pts', 0)

                return info

        return None

    async def _async_get_line_info(self, lines):
        _lines = deepcopy(lines)
        start_ts_path = self._get_first_ts_path(_lines)
        if not start_ts_path:
            return None
        _lines.reverse()
        end_ts_path = self._get_first_ts_path(_lines)
        if not end_ts_path:
            return None
        start_info = await self._async_get_top_line_info(start_ts_path)
        if not start_info:
            return None
        end_info = self._get_top_line_info(end_ts_path, stream_tags='start_pts')
        if not end_info:
            return None

        return {
            'tag': start_info['tag'],
            'start_pts': start_info['pts'],
            'end_pts': end_info['pts'],
        }

    @staticmethod
    def gen_cut_path(from_path):
        path = Path(from_path)
        return path.parent / f'{path.stem}_cut{path.suffix}'

    def generate_cut_m3u8(self, from_path, group_line_info):
        cut_file_path = self.gen_cut_path(from_path)

        needed_lines = []
        for entry in group_line_info:
            if entry.get('keep'):
                needed_lines.extend(entry['lines'])

        with open(cut_file_path, 'w') as f:
            for line in needed_lines:
                f.write(line)
                f.write('\n')

    def add_verify_stream_info(self, group_line_info):
        tag_duration = defaultdict(int)
        total_duration = 0
        for entry in group_line_info:
            info = entry.get('info')
            if not info:
                continue
            duration = entry.get('duration', 0)
            tag_duration[info['tag']] += duration
            total_duration += duration

        if total_duration == 0:
            return False

        tag_pass = {k: v / total_duration > 0.05 for k, v in tag_duration.items()}
        any_change = False
        for entry in group_line_info:
            info = entry.get('info')
            if info and tag_pass.get(info['tag']) is False:
                entry['keep'] = False
                any_change = True
            elif 'keep' not in entry:
                entry['keep'] = True

        if any_change:
            self.logger.info('Use Stream Info Cut')

        return any_change

    def add_verify_pts(self, group_line_info):
        info_groups = [x for x in group_line_info if x.get('info')]
        group_count = len(info_groups)
        max_segment_duration = 0
        total_duration = 0
        needed_ids = []
        for i in range(group_count):
            a_entry = info_groups[i]
            a_info = a_entry['info']
            prev_end = a_info['end_pts']
            guessed_ids = [a_entry['id']]
            seg_duration = a_entry.get('duration', 0)
            total_duration += seg_duration

            for j in range(i + 1, group_count):
                b_entry = info_groups[j]
                b_info = b_entry['info']

                if prev_end < b_info['start_pts']:
                    guessed_ids.append(b_entry['id'])
                    prev_end = b_info['start_pts']
                    seg_duration += b_entry.get('duration', 0)
            if seg_duration > max_segment_duration:
                max_segment_duration = seg_duration
                needed_ids = guessed_ids

        any_change = False
        if needed_ids and 1 - (max_segment_duration / total_duration) < 0.05:
            for entry in group_line_info:
                if not entry.get('info'):
                    continue
                if entry['id'] not in needed_ids:
                    entry['keep'] = False
                    any_change = True
                elif 'keep' not in entry:
                    entry['keep'] = True

        return any_change

    async def _run(self, file_path):
        groups = self._group_lines(file_path)

        group_infos = []
        tasks = []
        is_vod = False
        for idx, lines in enumerate(groups):
            duration = 0
            for line in lines:
                if line.strip().startswith('#EXTINF:'):
                    duration += float(line.strip()[8:].replace(',', ''))
                if line.strip() == '#EXT-X-PLAYLIST-TYPE:VOD':
                    is_vod = True

            tasks.append(self._async_get_line_info(lines))
            group_infos.append({'duration': duration, 'id': idx, 'lines': lines})

        info_list = await asyncio.gather(*tasks)
        for entry in group_infos:
            info = info_list[entry['id']]
            entry['info'] = info

        any_change = False
        if is_vod:
            any_change = self.add_verify_stream_info(group_infos)
            if not any_change:
                any_change = self.add_verify_pts(group_infos)

        if any_change:
            self.generate_cut_m3u8(file_path, group_infos)
            self.logger.info('Use PTS Cut')

        return any_change

    def cut(self, filePath):
        any_change = asyncio.run(self._run(filePath))
        return any_change
