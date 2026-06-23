"""
PyWebView API Bridge - 连接前端与后端
"""
import json
import threading
import os
import sys
import time
import tempfile
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from .tester import (
    BatchTester, IPEntry, parse_input,
    detect_proxy, export_results,
    CONNECTIVITY_TARGETS,
    test_connectivity,
)

# 持久化配置文件路径（存放在程序同目录）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_FILE = os.path.join(_BASE_DIR, "cfiptest_config.json")

# GitHub 仓库信息
GITHUB_REPO = "pcoof/cfiptest"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"


def _load_config() -> Dict:
    """读取本地配置文件"""
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_config(data: Dict):
    """保存配置到文件"""
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class Api:
    def __init__(self, version="2.0", window=None):
        self._window = window
        self._tester = BatchTester()
        self._entries: List[IPEntry] = []
        self._lock = threading.Lock()
        self._version = version
        # 加载持久化配置
        self._config = _load_config()

    def get_version(self) -> Dict:
        """返回当前版本号"""
        return {"version": self._version}

    def check_update(self) -> Dict:
        """检测 GitHub Releases 是否有新版本"""
        try:
            req = urllib.request.Request(
                f"{GITHUB_API}/releases/latest",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "cfiptest-updater",
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            latest_tag = data.get("tag_name", "").lstrip("v")
            if not latest_tag:
                return {"has_update": False, "error": "无法获取最新版本"}

            # 比较版本号（简单字符串比较，假设格式为 "2.0", "2.1" 等）
            has_update = self._compare_version(latest_tag, self._version)

            result = {
                "has_update": has_update,
                "current_version": self._version,
                "latest_version": latest_tag,
                "release_name": data.get("name", ""),
                "release_notes": data.get("body", ""),
                "html_url": data.get("html_url", ""),
            }

            # 查找 EXE 下载链接
            assets = data.get("assets", [])
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    result["download_url"] = asset.get("browser_download_url", "")
                    result["download_size"] = asset.get("size", 0)
                    break

            return result
        except Exception as e:
            return {"has_update": False, "error": str(e)}

    def _compare_version(self, v1: str, v2: str) -> bool:
        """返回 True 如果 v1 > v2"""
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]
            # 补齐长度
            max_len = max(len(parts1), len(parts2))
            parts1 += [0] * (max_len - len(parts1))
            parts2 += [0] * (max_len - len(parts2))
            return parts1 > parts2
        except Exception:
            return False

    def download_update(self, download_url: str) -> Dict:
        """
        下载更新并自动替换当前 EXE 后重启。
        返回 {"ok": True} 或 {"ok": False, "error": "..."}
        """
        try:
            # 获取当前 EXE 路径
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller 单文件模式：当前进程是解压后的临时 EXE
                # 实际 EXE 路径需要通过 sys.executable 获取
                current_exe = sys.executable
            else:
                current_exe = os.path.abspath(sys.argv[0])

            # 下载到临时文件
            tmp_dir = tempfile.gettempdir()
            tmp_file = os.path.join(tmp_dir, f"cfiptest_update_{int(time.time())}.exe")

            # 下载
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "cfiptest-updater"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(tmp_file, "wb") as f:
                    chunk = resp.read(8192)
                    while chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # 发送进度
                        if total_size > 0:
                            progress = int(downloaded / total_size * 100)
                            self._send("update_progress", {"progress": progress, "downloaded": downloaded, "total": total_size})
                        chunk = resp.read(8192)

            # 创建更新脚本（Windows batch）
            exe_dir = os.path.dirname(current_exe)
            bat_file = os.path.join(tmp_dir, f"cfiptest_update_{int(time.time())}.bat")

            bat_content = f"""@echo off
echo 正在更新 CF IP Tester...
timeout /t 2 /nobreak > nul
taskkill /f /im "{os.path.basename(current_exe)}" > nul 2>&1
timeout /t 1 /nobreak > nul
move /y "{tmp_file}" "{current_exe}" > nul
echo 更新完成，正在启动...
start "" "{current_exe}"
del "%~f0"
"""
            with open(bat_file, "w", encoding="utf-8") as f:
                f.write(bat_content)

            # 发送完成消息
            self._send("update_downloaded", {"bat_file": bat_file})

            # 启动更新脚本并退出
            os.startfile(bat_file)
            time.sleep(1)
            sys.exit(0)

            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_window(self, window):
        self._window = window

    # ── 发消息给前端 ──────────────────────────────
    def _send(self, event: str, data: Any = None):
        if self._window:
            payload = json.dumps({"event": event, "data": data})
            self._window.evaluate_js(f"window._cfBridge && window._cfBridge({payload!r})")

    # ── 代理检测 ──────────────────────────────────
    def check_proxy(self):
        result = detect_proxy()
        return result

    # ── 解析输入 ──────────────────────────────────
    def parse_entries(self, text: str) -> List[Dict]:
        self._entries = parse_input(text)
        return [self._entry_to_dict(e) for e in self._entries]

    # ── 开始测试 ──────────────────────────────────
    def start_test(self, text: str, options: Dict) -> Dict:
        self._entries = parse_input(text)
        if not self._entries:
            return {"ok": False, "msg": "没有有效的 IP/域名"}

        def progress(entry: IPEntry):
            self._send("progress", self._entry_to_dict(entry))

        def done():
            self._send("done", {"total": len(self._entries)})

        t = threading.Thread(
            target=self._tester.run,
            args=(self._entries, options, progress, done),
            daemon=True,
        )
        t.start()
        return {"ok": True, "total": len(self._entries)}

    # ── 停止测试 ──────────────────────────────────
    def stop_test(self):
        self._tester.stop()
        return {"ok": True}

    # ── 获取当前结果 ──────────────────────────────
    def get_results(self) -> List[Dict]:
        return [self._entry_to_dict(e) for e in self._entries]

    # ── 导出结果 ──────────────────────────────────
    def export_data(self, params: Dict) -> Dict:
        entries = self._entries
        # 处理仅导出选中
        selected = params.get("selected_addrs")
        if selected:
            entries = [e for e in entries if e.address in selected]
        text = export_results(
            entries,
            fmt=params.get("fmt", "edgetunnel"),
            export_fields=params.get("fields", ["country", "download", "ping"]),
            sort_by=params.get("sort_by", "ping"),
            ascending=params.get("ascending", True),
            only_success=params.get("only_success", True),
            top_n=params.get("top_n"),
        )
        return {"ok": True, "text": text}

    # ── 获取可用连通性目标列表 ────────────────────
    def get_connectivity_targets(self) -> List[str]:
        """返回内置 + 用户自定义目标"""
        builtin = list(CONNECTIVITY_TARGETS.keys())
        custom = self._config.get("custom_connectivity", [])
        # 合并，去重，保持顺序
        seen = set(builtin)
        result = builtin[:]
        for c in custom:
            name = c.get("name", "")
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def get_connectivity_targets_full(self) -> List[Dict]:
        """返回完整的连通性目标列表（包含自定义），每项含 name/host/port/builtin"""
        builtin = [
            {"name": k, "hosts": v, "builtin": True}
            for k, v in CONNECTIVITY_TARGETS.items()
        ]
        custom = [
            {**c, "builtin": False}
            for c in self._config.get("custom_connectivity", [])
        ]
        return builtin + custom

    def add_connectivity_target(self, name: str, host: str, port: int = 443) -> Dict:
        """添加自定义连通性目标"""
        custom = self._config.get("custom_connectivity", [])
        # 去重
        existing = [c for c in custom if c.get("name") != name]
        existing.append({"name": name, "host": host, "port": port})
        self._config["custom_connectivity"] = existing
        _save_config(self._config)
        # 动态注入到 CONNECTIVITY_TARGETS
        CONNECTIVITY_TARGETS[name] = [(host, port)]
        return {"ok": True}

    def remove_connectivity_target(self, name: str) -> Dict:
        """删除自定义连通性目标（内置不可删）"""
        custom = self._config.get("custom_connectivity", [])
        self._config["custom_connectivity"] = [c for c in custom if c.get("name") != name]
        _save_config(self._config)
        if name in CONNECTIVITY_TARGETS and name not in ["Cloudflare","Google","YouTube","GitHub","ChatGPT","Apple","Telegram"]:
            del CONNECTIVITY_TARGETS[name]
        return {"ok": True}

    # ── 运行连通性测试 ────────────────────────────
    def run_connectivity_test(self, targets: List[str]) -> Dict:
        """直接测试连通性，返回结果"""
        # 先确保自定义目标已注入
        for c in self._config.get("custom_connectivity", []):
            name = c.get("name", "")
            if name and name not in CONNECTIVITY_TARGETS:
                CONNECTIVITY_TARGETS[name] = [(c.get("host", name), c.get("port", 443))]
        results = test_connectivity(targets, timeout=5.0)
        return {"ok": True, "results": results}

    # ── 保存/恢复 配置 ────────────────────────────
    def save_settings(self, settings: Dict) -> Dict:
        """保存前端设置（选项、列显示、连通性选择等）"""
        self._config["settings"] = settings
        _save_config(self._config)
        return {"ok": True}

    def load_settings(self) -> Dict:
        """加载保存的设置"""
        return self._config.get("settings", {})

    def save_ip_list(self, text: str) -> Dict:
        """保存 IP 列表历史"""
        history = self._config.get("ip_list_history", [])
        # 保留最近 5 条
        import time as _time
        history.insert(0, {"text": text, "time": int(_time.time())})
        self._config["ip_list_history"] = history[:5]
        _save_config(self._config)
        return {"ok": True}

    def load_ip_list(self) -> Dict:
        """加载最近保存的 IP 列表"""
        history = self._config.get("ip_list_history", [])
        if history:
            return {"ok": True, "text": history[0]["text"], "history": history}
        return {"ok": False, "text": "", "history": []}

    def update_entries(self, updates: List[Dict]) -> Dict:
        """从前端接收条目更新（如备注清除），同步到后端 _entries"""
        for u in updates:
            addr = u.get("address")
            port = u.get("port")
            for e in self._entries:
                if e.address == addr and e.port == port:
                    if "remark" in u:
                        e.remark = u["remark"]
                    break
        return {"ok": True}

    # ── 内部：entry 转 dict ───────────────────────
    def _entry_to_dict(self, e: IPEntry) -> Dict:
        return {
            "address": e.address,
            "port": e.port,
            "remark": e.remark,
            "ping_ms": e.ping_ms,
            "download_speed": e.download_speed,
            "country": e.country,
            "country_code": e.country_code,
            "city": e.city,
            "isp": e.isp,
            "asn": e.asn,
            "telecom_ms": e.telecom_ms,
            "mobile_ms": e.mobile_ms,
            "unicom_ms": e.unicom_ms,
            "connectivity": e.connectivity,
            "status": e.status,
            "error": e.error,
        }
