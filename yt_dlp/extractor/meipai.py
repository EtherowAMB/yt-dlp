import base64
import re
import struct

from .common import InfoExtractor
from ..utils import (
    int_or_none,
    parse_duration,
    unified_timestamp,
)


def _decode_meipai_url(encoded):
    """
    复现站点 JavaScript 中的 decodeMp4 函数（来自 meipai.pc.v1.min.js）：

        getHex:  str[:4] 反转 → hex  ;  str[4:] → body
        getDec:  int(hex, 16) → 十进制字符串 → pre[0:2], tail[2:]
        substr:  从 body 中删掉 pre 指定的子串
        getPos:  计算 tail 在 body 中的偏移
        decode:  最终 base64 解码
    """
    hex_str = encoded[:4][::-1]          # 前4字符反转作为hex
    body = encoded[4:]                    # 剩余部分
    dec = str(int(hex_str, 16))          # hex → 十进制字符串
    pre = [int(dec[0]), int(dec[1])]     # 前两位数字
    tail = [int(dec[2]), int(dec[3])]   # 后两位数字

    # substr: 删掉 body[pre[0] : pre[0]+pre[1]]
    c = body[:pre[0]]
    d = body[pre[0]:pre[0] + pre[1]]
    stripped = c + body[pre[0]:].replace(d, '', 1)

    # getPos: tail[0] = len(stripped) - tail[0] - tail[1]
    tail[0] = len(stripped) - tail[0] - tail[1]

    # 再做一次 substr 删除（用 tail 作偏移）
    c2 = stripped[:tail[0]]
    d2 = stripped[tail[0]:tail[0] + tail[1]]
    base64_str = c2 + stripped[tail[0]:].replace(d2, '', 1)

    decoded = base64.b64decode(base64_str).decode('utf-8')
    # 补全协议前缀（站点返回的 URL 以 // 开头）
    if decoded.startswith('//'):
        decoded = 'https:' + decoded
    return decoded


class MeipaiIE(InfoExtractor):
    IE_DESC = '美拍单个视频'
    # _VALID_URL = r'https?://(?:www\.)?meipai\.com/media/(?P<id>[0-9]+)'
    _VALID_URL = r'https?://(?:www\.)?meipai\.com/(?:media|video/\d+)/(?P<id>\d+)'
    _TESTS = [{
        # regular uploaded video
        'url': 'http://www.meipai.com/media/531697625',
        'md5': 'e3e9600f9e55a302daecc90825854b4f',
        'info_dict': {
            'id': '531697625',
            'ext': 'mp4',
            'title': '#葉子##阿桑##余姿昀##超級女聲#',
            'description': '#葉子##阿桑##余姿昀##超級女聲#',
            'thumbnail': r're:^https?://.*\.jpg$',
            'duration': 152,
            'timestamp': 1465492420,
            'upload_date': '20160609',
            'view_count': 35511,
            'creator': '她她-TATA',
            'tags': ['葉子', '阿桑', '余姿昀', '超級女聲'],
        },
    }, {
        # record of live streaming
        'url': 'http://www.meipai.com/media/585526361',
        'md5': 'ff7d6afdbc6143342408223d4f5fb99a',
        'info_dict': {
            'id': '585526361',
            'ext': 'mp4',
            'title': '姿昀和善願 練歌練琴啦😁😁😁',
            'description': '姿昀和善願 練歌練琴啦😁😁😁',
            'thumbnail': r're:^https?://.*\.jpg$',
            'duration': 5975,
            'timestamp': 1474311799,
            'upload_date': '20160919',
            'view_count': 1215,
            'creator': '她她-TATA',
        },
    }]

    def _extract_dimensions(self, url, video_id):
        try:
            req = self._request_webpage(
                url, video_id, note='Extracting video dimensions',
                headers={'Range': 'bytes=0-50000'}, fatal=False)
            if req:
                data = req.read()
                idx = 0
                while True:
                    idx = data.find(b'tkhd', idx)
                    if idx == -1: break
                    version = data[idx+4]
                    offset = idx + 8 + (32 if version == 1 else 20) + 16 + 36
                    w = struct.unpack('>I', data[offset:offset+4])[0] >> 16
                    h = struct.unpack('>I', data[offset+4:offset+8])[0] >> 16
                    if w > 0 and h > 0:
                        return w, h
                    idx += 4
        except Exception:
            pass
        return None, None

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)
        '''
        # 从网页中正则匹配 <h1 class="detail-cover-title ..."> 标签里的所有内容
        title_html = self._html_search_regex(
            r'<h1[^>]+class=["\'][^"\']*detail-cover-title[^"\']*["\'][^>]*>([\s\S]+?)</h1>',
            webpage, 'title', default=None)
        
        if title_html:
            # 去除内部可能包含的 HTML 标签（比如你看到的 <span class="emoji..."></span>），并去掉首尾空格换行
            title = re.sub(r'<[^>]+>', '', title_html).strip()
        else:
            # 如果极端情况下没找到，再用废话标题兜底
            title = self._generic_title('', webpage)
        '''

        # 先尝试获取正经的标题
        title_html = self._html_search_regex(
            r'<h1[^>]+class=["\'][^"\']*detail-cover-title[^"\']*["\'][^>]*>([\s\S]+?)</h1>',
            webpage, 'title', default=None)
        
        title = None
        if title_html:
            # 去除内部包含的 HTML 标签，并去掉首尾空格
            title = re.sub(r'<[^>]+>', '', title_html).strip()

        # 如果正经标题不存在或为空，尝试获取描述 (detail-description)
        if not title:
            desc_html = self._html_search_regex(
                r'<h1[^>]+class=["\'][^"\']*detail-description[^"\']*["\'][^>]*>([\s\S]+?)</h1>',
                webpage, 'description', default=None)
            
            if desc_html:
                # 去除HTML标签（比如话题链接 <a>）
                clean_desc = re.sub(r'<[^>]+>', '', desc_html)
                # 把换行和回车替换成空格，防止文件名断层
                clean_desc = re.sub(r'[\r\n]+', ' ', clean_desc)
                # 去除 Windows 不能作为文件名的特殊字符：\ / : * ? " < > |
                clean_desc = re.sub(r'[\\/:*?"<>|]', '', clean_desc)
                # 去除首尾空白
                clean_desc = clean_desc.strip()
                
                # 截取前 50 个字符
                if clean_desc:
                    title = clean_desc[:50]

        # 如果经过以上处理依然是空（如去除了非法字符后啥也不剩了），再用原程序的废话标题兜底
        if not title:
            title = self._generic_title('', webpage)

        formats = []

        # recorded playback of live streaming
        m3u8_url = self._html_search_regex(
            r'file:\s*encodeURIComponent\((["\'])(?P<url>(?:(?!\1).)+)\1\)',
            webpage, 'm3u8 url', group='url', default=None)
        if m3u8_url:
            formats.extend(self._extract_m3u8_formats(
                m3u8_url, video_id, 'mp4', entry_protocol='m3u8_native',
                m3u8_id='hls', fatal=False))

        width, height = None, None

        if not formats:
            # 尝试经过 decodeMp4 混淆的视频地址
            encoded_url = self._search_regex(
                r'vcastr_file["\']?\s*:\s*(["\'])(?P<url>(?:(?!\1).)+)\1',
                webpage, 'encoded video url', group='url', default=None)
            if encoded_url:
                try:
                    real_url = _decode_meipai_url(encoded_url)
                    w, h = self._extract_dimensions(real_url, video_id)
                    if w and h:
                        width, height = w, h
                    formats.append({
                        'url': real_url,
                        'format_id': 'http',
                        'width': width,
                        'height': height,
                    })
                except Exception:
                    pass

        if not formats:
            # regular uploaded video (old pattern)
            video_url = self._search_regex(
                r'data-video=(["\'])(?P<url>(?:(?!\1).)+)\1', webpage, 'video url',
                group='url', default=None)
            if video_url:
                try:
                    real_url = _decode_meipai_url(video_url)
                except Exception:
                    real_url = video_url
                w, h = self._extract_dimensions(real_url, video_id)
                if w and h:
                    width, height = w, h
                formats.append({
                    'url': real_url,
                    'format_id': 'http',
                    'width': width,
                    'height': height,
                })

        timestamp = unified_timestamp(self._og_search_property(
            'video:release_date', webpage, 'release date', default=None))

        tags = self._og_search_property(
            'video:tag', webpage, 'tags', default='').split(',')

        view_count = int_or_none(self._html_search_meta(
            'interactionCount', webpage, 'view count', default=None))
        duration = parse_duration(self._html_search_meta(
            'duration', webpage, 'duration', default=None))
        creator = self._og_search_property(
            'video:director', webpage, 'creator', default=None)

        aspect_ratio = None
        if width and height:
            aspect_ratio = width / height

        return {
            'id': video_id,
            'title': title,
            'description': self._og_search_description(webpage),
            'thumbnail': self._og_search_thumbnail(webpage),
            'duration': duration,
            'timestamp': timestamp,
            'view_count': view_count,
            'creator': creator,
            'tags': tags,
            'formats': formats,
            'width': width,
            'height': height,
            'aspect_ratio': aspect_ratio,
        }


class MeipaiUserIE(InfoExtractor):
    IE_DESC = '美拍用户主页（自动翻页下载全部视频）'
    # 匹配两种用户主页 URL：
    #   https://www.meipai.com/user/1822566240
    #   https://www.meipai.com/user/1822566240?single_column=0&p=2
    _VALID_URL = r'https?://(?:www\.)?meipai\.com/user/(?P<id>\d+)(?:[?#].*)?$'
    _TESTS = [{
        'url': 'https://www.meipai.com/user/1822566240',
        'info_dict': {
            'id': '1822566240',
            'title': str,
        },
        'playlist_mincount': 1,
    }]

    # 让 MeipaiIE 先尝试，只有 /user/ 才落到这里
    @classmethod
    def suitable(cls, url):
        return (
            re.match(cls._VALID_URL, url) is not None
            and not MeipaiIE.suitable(url)
        )

    def _extract_page_entries(self, webpage, user_id):
        """从单页 HTML 中提取所有不重复的 /media/<id> 链接。"""
        # 使用 dict.fromkeys 保序去重
        media_ids = list(dict.fromkeys(
            re.findall(
                r'href=["\'](?:https?://(?:www\.)?meipai\.com)?/media/(\d+)["\']',
                webpage,
            )
        ))
        entries = []
        for mid in media_ids:
            video_url = f'https://www.meipai.com/media/{mid}'
            entries.append(self.url_result(video_url, ie=MeipaiIE.ie_key(), video_id=mid))
        return entries

    def _get_next_page_url(self, webpage):
        """返回下一页的绝对 URL，若无下一页则返回 None。"""
        # HTML: <a hidefocus href="/user/ID?p=N" class="paging-next dbl">下一页</a>
        m = re.search(
            r'href=["\']([^"\']+)["\'][^>]*class=[^>]*paging-next',
            webpage,
        )
        if not m:
            return None
        path = m.group(1)
        if path.startswith('http'):
            return path
        return 'https://www.meipai.com' + path

    def _real_extract(self, url):
        user_id = self._match_id(url)

        # 始终从第 1 页（不带 p= 参数）开始，确保完整收录
        first_url = f'https://www.meipai.com/user/{user_id}?single_column=0'

        def _entries():
            page_url = first_url
            page_num = 1
            while page_url:
                webpage = self._download_webpage(
                    page_url, user_id,
                    note=f'正在下载第 {page_num} 页',
                    errnote=f'第 {page_num} 页下载失败')

                page_entries = self._extract_page_entries(webpage, user_id)
                if not page_entries:
                    self.to_screen(f'第 {page_num} 页没有视频，停止翻页')
                    break

                self.to_screen(f'第 {page_num} 页找到 {len(page_entries)} 个视频')
                yield from page_entries

                next_url = self._get_next_page_url(webpage)
                if not next_url:
                    self.to_screen('已到最后一页，完成')
                    break

                page_url = next_url
                page_num += 1

        # 获取第一页用于提取 playlist 标题
        first_page = self._download_webpage(
            first_url, user_id, note='下载用户主页（获取标题）')
        title = (
            self._html_search_regex(
                r'<h2[^>]*class=[^>]*content-l-h2[^>]*>\s*([^<]+)\s*</h2>',
                first_page, 'username', default=None)
            or self._html_search_regex(
                r'<h2[^>]*>\s*([^<]+)\s*</h2>',
                first_page, 'username', default=user_id)
        )
        
        # 核心修改：如果标题以“的美拍”结尾，就裁剪掉最后三个字
        if title and title.endswith('的美拍'):
            title = title[:-3]

        return self.playlist_result(
            _entries(), playlist_id=user_id, playlist_title=title)
