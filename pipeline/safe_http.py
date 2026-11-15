"""出站请求安全校验：只允许 http/https，拒绝 localhost / 环回 / 私有 / 保留地址。

聚合源和上游配置都来自外部 JSON，不能直接当可信 URL 用。
所有脚本统一走 safe_http.open_request()，避免每个文件各写一份校验。
"""
import socket
import urllib.parse
import urllib.request
from ipaddress import ip_address

_CACHE = {}


def safe_url(url):
    try:
        p = urllib.parse.urlsplit(str(url))
    except Exception:
        return False
    if p.scheme not in ('http', 'https') or not p.hostname:
        return False
    host = p.hostname.strip('[]').lower()
    if host == 'localhost' or host.endswith(('.local', '.internal', '.lan')):
        return False
    if host in _CACHE:
        return _CACHE[host]
    try:
        ip = ip_address(host)
        ok = not (ip.is_private or ip.is_loopback or ip.is_link_local
                  or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        ok = True
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ip_address(info[4][0])
                if (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                    ok = False
                    break
        except Exception:
            pass          # DNS 解析失败交给请求本身报错，不因抖动丢源
    if len(_CACHE) > 512:
        _CACHE.clear()
    _CACHE[host] = ok
    return ok


def open_request(req, timeout=10, context=None):
    """对 urllib.request.Request 做安全校验后再发请求。"""
    if not safe_url(getattr(req, 'full_url', req)):
        raise ValueError('unsafe url')
    if context is not None:
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    return urllib.request.urlopen(req, timeout=timeout)


def open_url(url, timeout=10, context=None, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    return open_request(req, timeout=timeout, context=context)
