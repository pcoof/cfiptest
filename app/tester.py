"""
CF IP 优选测试引擎
支持：延迟测试、下载测速、国家检测、运营商检测、网络连通性测试
"""
import asyncio
import time
import socket
import ssl
import urllib.request
import urllib.error
import urllib.parse
import json
import threading
import re
import ipaddress
from typing import Optional, Dict, Any, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict

# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class IPEntry:
    raw: str            # 原始行
    address: str        # IP 或域名（不含端口）
    port: int = 443
    remark: str = ""    # #后面的备注

    # 测试结果
    ping_ms: Optional[float] = None
    download_speed: Optional[float] = None   # Mbps
    country: Optional[str] = None
    country_code: Optional[str] = None
    isp: Optional[str] = None
    asn: Optional[str] = None
    city: Optional[str] = None

    # 运营商连通
    telecom_ms: Optional[float] = None
    mobile_ms: Optional[float] = None
    unicom_ms: Optional[float] = None

    # 网络连通性
    connectivity: Dict[str, Any] = field(default_factory=dict)

    # 状态
    status: str = "pending"   # pending / testing / done / error
    error: str = ""


# ─────────────────────────────────────────────
# 解析输入行
# ─────────────────────────────────────────────
def parse_line(line: str) -> Optional[IPEntry]:
    """解析一行地址，支持 IP:port#remark / [IPv6]:port#remark / domain#remark
    以 # 或 // 开头的行视为注释，http(s):// 开头的行是远程 URL（由 parse_input 处理）。
    """
    line = line.strip()
    # 空行 / 注释行
    if not line or line.startswith("#") or line.startswith("//"):
        return None
    # 远程 URL 行由上层统一拉取，这里不再处理
    if line.lower().startswith("http://") or line.lower().startswith("https://"):
        return None

    remark = ""
    if "#" in line:
        idx = line.index("#")
        remark = line[idx + 1:].strip()
        line = line[:idx].strip()

    if not line:
        return None

    # IPv6 带括号：[2606:4700::]:2053
    ipv6_port_re = re.match(r"^\[([^\]]+)\]:?(\d+)?$", line)
    if ipv6_port_re:
        addr = ipv6_port_re.group(1)
        port = int(ipv6_port_re.group(2)) if ipv6_port_re.group(2) else 443
        return IPEntry(raw=f"{line}#{remark}", address=addr, port=port, remark=remark)

    # 普通 host:port
    if ":" in line:
        parts = line.rsplit(":", 1)
        if parts[1].isdigit():
            return IPEntry(raw=f"{line}#{remark}", address=parts[0], port=int(parts[1]), remark=remark)

    return IPEntry(raw=f"{line}#{remark}", address=line, port=443, remark=remark)


def _fetch_url_text(url: str, timeout: float = 10.0) -> str:
    """拉取远程文本内容，失败返回空字符串"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cfiptest/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # 尝试 utf-8，fallback latin-1
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
    except Exception:
        return ""


def expand_text(text: str) -> str:
    """
    将输入文本中的 http(s):// 行替换为远程拉取到的内容。
    注释行（# / //）保留原样（后续 parse_line 会跳过）。
    返回展开后的完整文本，保留原有非 URL 行。
    """
    lines_out: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("http://") or stripped.lower().startswith("https://"):
            # 取 # 前的 URL，# 后视为对该 URL 的注释/标签（不作为地址备注）
            url = stripped.split("#")[0].strip()
            fetched = _fetch_url_text(url)
            if fetched:
                lines_out.append(f"# === 来自 {url} ===")
                lines_out.append(fetched.strip())
            # 若拉取失败则静默跳过（不把 URL 本身当成 IP）
        else:
            lines_out.append(line)
    return "\n".join(lines_out)


def parse_input(text: str) -> List[IPEntry]:
    """解析输入文本（先展开远程 URL）"""
    expanded = expand_text(text)
    entries = []
    seen = set()
    for line in expanded.splitlines():
        e = parse_line(line)
        if e and e.address not in seen:
            seen.add(e.address)
            entries.append(e)
    return entries


# ─────────────────────────────────────────────
# 代理 / VPN 检测
# ─────────────────────────────────────────────
def detect_proxy() -> Dict[str, Any]:
    """检测系统当前是否启用了代理/VPN/TUN"""
    result = {
        "has_proxy": False,
        "proxy_type": [],
        "details": {}
    }

    import os, sys, platform

    # 1. 检测环境变量代理
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        val = os.environ.get(var, "")
        if val:
            result["has_proxy"] = True
            result["proxy_type"].append(f"env:{var}={val}")
            result["details"][var] = val

    # 2. 检测系统代理（Windows）
    if sys.platform == "win32":
        try:
            import winreg
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                proxy_server_val = ""
                proxy_enabled = 0

                # 读取 ProxyEnable
                try:
                    proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                except FileNotFoundError:
                    pass

                # 读取 ProxyServer
                try:
                    proxy_server_val, _ = winreg.QueryValueEx(key, "ProxyServer")
                except FileNotFoundError:
                    pass

                # 条件1：ProxyEnable=1，系统代理明确开启
                if proxy_enabled and proxy_server_val:
                    result["has_proxy"] = True
                    result["proxy_type"].append(f"system:{proxy_server_val}")
                    result["details"]["system_proxy"] = proxy_server_val

                # 条件2：ProxyEnable=0 但 ProxyServer 非空且端口在监听
                # （Clash/V2Ray 等工具设置了代理但未通过 ProxyEnable 控制）
                elif proxy_server_val and not proxy_enabled:
                    # 检查端口是否在监听
                    _host_port = proxy_server_val.rsplit(":", 1)
                    if len(_host_port) == 2 and _host_port[1].isdigit():
                        _p = int(_host_port[1])
                        _listening = _check_port_listening("127.0.0.1", _p)
                    else:
                        _listening = False
                    if _listening:
                        result["has_proxy"] = True
                        result["proxy_type"].append(f"system:{proxy_server_val}")
                        result["details"]["system_proxy"] = proxy_server_val
                        result["details"]["note"] = "ProxyEnable=0 但端口在监听（Clash/代理软件已启动）"

                # 2b. PAC 自动配置代理（AutoConfigURL）
                try:
                    pac_url, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                    if pac_url and pac_url.strip():
                        result["has_proxy"] = True
                        result["proxy_type"].append(f"pac:{pac_url}")
                        result["details"]["pac_url"] = pac_url
                except FileNotFoundError:
                    pass
        except Exception:
            pass

    # 3. 检测常见代理端口是否在监听（兜底：即使注册表无记录）
    if sys.platform == "win32" and not result["has_proxy"]:
        _common_ports = [7890, 7891, 7892, 1080, 10808, 8080, 8888, 1087, 1086]
        for _cp in _common_ports:
            if _check_port_listening("127.0.0.1", _cp):
                result["has_proxy"] = True
                result["proxy_type"].append(f"local:{_cp}")
                result["details"]["local_port"] = _cp
                break

    # 4. 检测 TUN 网卡（进程名或网卡名含关键词）
    try:
        import subprocess
        if sys.platform == "win32":
            out = subprocess.check_output(["ipconfig"], encoding="gbk", errors="ignore", timeout=3)
            for line in out.splitlines():
                if any(k in line.lower() for k in ["tun", "tap", "clash", "wintun", "utun", "meta"]):
                    result["has_proxy"] = True
                    result["proxy_type"].append(f"tun:{line.strip()}")
                    result["details"]["tun"] = line.strip()
                    break
        else:
            out = subprocess.check_output(["ifconfig"], encoding="utf-8", errors="ignore", timeout=3)
            for line in out.splitlines():
                if any(k in line.lower() for k in ["tun", "tap", "utun", "wg0", "clash"]):
                    result["has_proxy"] = True
                    result["proxy_type"].append(f"tun:{line.strip()}")
                    result["details"]["tun"] = line.strip()
                    break
    except Exception:
        pass

    return result


def _check_port_listening(host: str, port: int, timeout: float = 0.3) -> bool:
    """快速检测本地端口是否有进程在监听"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# TCP 延迟测试
# ─────────────────────────────────────────────
def tcp_ping(host: str, port: int, timeout: float = 3.0, count: int = 3) -> Optional[float]:
    """TCP 握手延迟，返回平均值(ms)，失败返回 None"""
    times = []
    for _ in range(count):
        try:
            start = time.perf_counter()
            with socket.create_connection((host, port), timeout=timeout):
                pass
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
        except Exception:
            pass
    if not times:
        return None
    return round(sum(times) / len(times), 2)


# ─────────────────────────────────────────────
# 国家 / ISP 查询（通过 ip-api.com）
# ─────────────────────────────────────────────
def get_ip_info(address: str, timeout: float = 5.0) -> Dict[str, Any]:
    """查询 IP 地理信息，支持 IPv4/IPv6/域名"""
    try:
        # ip-api.com 免费，支持 IPv4/IPv6
        url = f"http://ip-api.com/json/{urllib.parse.quote(address)}?fields=status,country,countryCode,city,isp,org,as"
        req = urllib.request.Request(url, headers={"User-Agent": "cfiptest/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return {
                    "country": data.get("country", ""),
                    "country_code": data.get("countryCode", ""),
                    "city": data.get("city", ""),
                    "isp": data.get("isp", ""),
                    "asn": data.get("as", ""),
                }
    except Exception:
        pass
    return {}


# ─────────────────────────────────────────────
# 下载速度测试（Cloudflare 测速文件）
# ─────────────────────────────────────────────
def test_download_speed(
    host: str,
    port: int,
    timeout: float = 10.0,
    test_url_path: str = "/cdn-cgi/trace",
    download_size_mb: float = 5.0,
) -> Optional[float]:
    """
    通过 HTTPS 连接到目标 IP，测试下载速度(Mbps)。
    使用 Cloudflare speed.cloudflare.com 的测速文件。
    """
    # 直接测试目标 IP 的 HTTPS 响应速度（用 __cf_chl_jschl_tk__ 方式不实际，改用简单文件下载）
    # 对目标 IP 建立 TLS 连接并下载 /cdn-cgi/trace 来验证可达性，然后测速
    try:
        # 构造 raw socket + TLS 请求
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # 用 HTTP/1.1 GET 请求下载一个大文件
        # Cloudflare 标准测速地址
        sizes = {1: "1mb", 5: "5mb", 10: "10mb", 25: "25mb", 100: "100mb"}
        # 选最近的 size
        chosen = "5mb"
        for s_mb, s_name in sizes.items():
            if download_size_mb <= s_mb:
                chosen = s_name
                break

        url = f"https://{host}:{port}/__down?bytes={int(download_size_mb*1024*1024)}"

        req = urllib.request.Request(
            url,
            headers={
                "Host": "speed.cloudflare.com",
                "User-Agent": "cfiptest/1.0",
            }
        )
        # 为了绕过证书检查
        handler = urllib.request.HTTPSHandler(context=context)
        opener = urllib.request.build_opener(handler)

        start = time.perf_counter()
        total_bytes = 0
        with opener.open(req, timeout=timeout) as resp:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
        elapsed = time.perf_counter() - start

        if total_bytes > 0 and elapsed > 0:
            speed_mbps = (total_bytes * 8) / (elapsed * 1_000_000)
            return round(speed_mbps, 2)
    except Exception:
        pass

    # 备用：测试 /cdn-cgi/trace 响应时间，根据响应大小估算
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        handler = urllib.request.HTTPSHandler(context=context)
        opener = urllib.request.build_opener(handler)

        url = f"https://{host}:{port}/cdn-cgi/trace"
        req = urllib.request.Request(url, headers={
            "Host": "www.cloudflare.com",
            "User-Agent": "cfiptest/1.0",
        })
        start = time.perf_counter()
        total_bytes = 0
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            total_bytes = len(data)
        elapsed = time.perf_counter() - start
        if total_bytes > 100 and elapsed > 0:
            speed_mbps = (total_bytes * 8) / (elapsed * 1_000_000)
            return round(speed_mbps, 3)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# 网络连通性测试
# ─────────────────────────────────────────────
CONNECTIVITY_TARGETS = {
    "Cloudflare": [("1.1.1.1", 443), ("cloudflare.com", 443)],
    "Google":     [("8.8.8.8", 443), ("google.com", 443)],
    "YouTube":    [("youtube.com", 443)],
    "GitHub":     [("github.com", 443)],
    "ChatGPT":    [("chat.openai.com", 443)],
    "Apple":      [("apple.com", 443)],
    "Telegram":   [("149.154.167.51", 443), ("t.me", 443)],
}


def test_connectivity(targets: List[str], timeout: float = 4.0) -> Dict[str, Any]:
    """测试指定目标的可达性"""
    results = {}
    for name in targets:
        if name not in CONNECTIVITY_TARGETS:
            continue
        addrs = CONNECTIVITY_TARGETS[name]
        ok = False
        latency = None
        for host, port in addrs:
            ms = tcp_ping(host, port, timeout=timeout, count=1)
            if ms is not None:
                ok = True
                latency = ms
                break
        results[name] = {"ok": ok, "latency_ms": latency}
    return results


# ─────────────────────────────────────────────
# 运营商延迟（通过各运营商 DNS 服务器 TCP 连接模拟）
# ─────────────────────────────────────────────
ISP_PROBES = {
    "telecom": [("101.226.4.6", 53), ("180.76.76.76", 53)],   # 电信 DNS
    "mobile":  [("223.5.5.5", 53), ("120.196.165.7", 53)],    # 移动 DNS
    "unicom":  [("119.29.29.29", 53), ("210.22.84.3", 53)],   # 联通 DNS
}

def test_isp_latency(timeout: float = 3.0) -> Dict[str, Optional[float]]:
    results = {}
    for isp, probes in ISP_PROBES.items():
        for host, port in probes:
            ms = tcp_ping(host, port, timeout=timeout, count=2)
            if ms is not None:
                results[isp] = ms
                break
        if isp not in results:
            results[isp] = None
    return results


# ─────────────────────────────────────────────
# 主测试函数（单个 IP）
# ─────────────────────────────────────────────
def test_single(
    entry: IPEntry,
    options: Dict[str, Any],
    progress_cb: Optional[Callable] = None,
) -> IPEntry:
    """对单个 IP 进行完整测试，就地修改 entry 并返回"""
    entry.status = "testing"
    try:
        # 1. TCP 延迟
        entry.ping_ms = tcp_ping(
            entry.address, entry.port,
            timeout=options.get("ping_timeout", 3.0),
            count=options.get("ping_count", 3),
        )

        if entry.ping_ms is None:
            entry.status = "error"
            entry.error = "TCP 连接超时"
            if progress_cb:
                progress_cb(entry)
            return entry

        # 2. 地理 / ISP 信息
        if options.get("geo", True):
            info = get_ip_info(entry.address, timeout=5.0)
            entry.country = info.get("country", "")
            entry.country_code = info.get("country_code", "")
            entry.city = info.get("city", "")
            entry.isp = info.get("isp", "")
            entry.asn = info.get("asn", "")

        # 3. 下载速度
        if options.get("download", True):
            entry.download_speed = test_download_speed(
                entry.address, entry.port,
                timeout=options.get("download_timeout", 10.0),
                download_size_mb=options.get("download_size_mb", 5.0),
            )

        # 4. 运营商延迟（三项独立控制）
        if options.get("isp_test", True):
            isp_r = test_isp_latency(timeout=3.0)
            # 每项独立判断是否需要测试
            if not options.get("telecom", True):
                isp_r["telecom"] = None
            if not options.get("mobile", True):
                isp_r["mobile"] = None
            if not options.get("unicom", True):
                isp_r["unicom"] = None
            entry.telecom_ms = isp_r.get("telecom")
            entry.mobile_ms  = isp_r.get("mobile")
            entry.unicom_ms  = isp_r.get("unicom")

        # 5. 网络连通性
        conn_targets = options.get("connectivity_targets", [])
        if conn_targets:
            entry.connectivity = test_connectivity(conn_targets, timeout=4.0)

        entry.status = "done"
    except Exception as ex:
        entry.status = "error"
        entry.error = str(ex)

    if progress_cb:
        progress_cb(entry)
    return entry


# ─────────────────────────────────────────────
# 批量测试控制器
# ─────────────────────────────────────────────
class BatchTester:
    def __init__(self):
        self._stop_event = threading.Event()
        self._executor: Optional[ThreadPoolExecutor] = None

    def stop(self):
        self._stop_event.set()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def run(
        self,
        entries: List[IPEntry],
        options: Dict[str, Any],
        progress_cb: Optional[Callable] = None,
        done_cb: Optional[Callable] = None,
    ):
        self._stop_event.clear()
        concurrency = options.get("concurrency", 8)
        self._executor = ThreadPoolExecutor(max_workers=concurrency)

        futures = {}
        for entry in entries:
            if self._stop_event.is_set():
                break
            future = self._executor.submit(test_single, entry, options, progress_cb)
            futures[future] = entry

        for future in as_completed(futures):
            if self._stop_event.is_set():
                break
            try:
                future.result()
            except Exception:
                pass

        self._executor.shutdown(wait=False)
        if done_cb:
            done_cb()


# ─────────────────────────────────────────────
# 导出功能
# ─────────────────────────────────────────────
def format_export_line(entry: IPEntry, export_fields: List[str]) -> str:
    """
    格式：address:port#name|field1|field2|...
    按 edgetunnel 格式，#后为备注，|分隔附加字段
    """
    # 地址部分
    is_ipv6 = False
    try:
        ipaddress.IPv6Address(entry.address)
        is_ipv6 = True
    except ValueError:
        pass

    if is_ipv6:
        addr_part = f"[{entry.address}]:{entry.port}"
    else:
        addr_part = f"{entry.address}:{entry.port}"

    # 备注 / 名称
    name_parts = []
    if entry.remark:
        name_parts.append(entry.remark)

    # 附加字段
    field_map = {
        "country":   entry.country or "",
        "city":      entry.city or "",
        "isp":       entry.isp or "",
        "ping":      f"{entry.ping_ms}ms" if entry.ping_ms is not None else "",
        "download":  f"{entry.download_speed}Mbps" if entry.download_speed is not None else "",
        "telecom":   f"电信{entry.telecom_ms}ms" if entry.telecom_ms is not None else "",
        "mobile":    f"移动{entry.mobile_ms}ms" if entry.mobile_ms is not None else "",
        "unicom":    f"联通{entry.unicom_ms}ms" if entry.unicom_ms is not None else "",
    }
    for f in export_fields:
        val = field_map.get(f, "")
        if val:
            name_parts.append(val)

    remark_str = "|".join(filter(None, name_parts))
    return f"{addr_part}#{remark_str}"


def export_results(
    entries: List[IPEntry],
    fmt: str = "edgetunnel",
    export_fields: Optional[List[str]] = None,
    sort_by: str = "ping",
    ascending: bool = True,
    only_success: bool = True,
    top_n: Optional[int] = None,
) -> str:
    """生成导出文本"""
    if export_fields is None:
        export_fields = ["country", "download", "ping"]

    # 筛选
    if only_success:
        entries = [e for e in entries if e.status == "done"]

    # 排序
    def sort_key(e):
        if sort_by == "ping":
            return e.ping_ms if e.ping_ms is not None else 99999
        if sort_by == "download":
            return -(e.download_speed or 0)
        if sort_by == "country":
            return e.country or "zzz"
        return 0

    entries = sorted(entries, key=sort_key, reverse=not ascending)

    if top_n:
        entries = entries[:top_n]

    lines = []
    for e in entries:
        if fmt == "edgetunnel":
            lines.append(format_export_line(e, export_fields))
        else:
            # CSV
            lines.append(
                f"{e.address},{e.port},{e.remark},{e.country or ''},{e.ping_ms or ''},"
                f"{e.download_speed or ''},{e.isp or ''}"
            )

    return "\n".join(lines)
