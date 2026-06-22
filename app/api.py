"""
PyWebView API Bridge - 连接前端与后端
"""
import json
import threading
import os
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
    def __init__(self, window=None):
        self._window = window
        self._tester = BatchTester()
        self._entries: List[IPEntry] = []
        self._lock = threading.Lock()
        # 加载持久化配置
        self._config = _load_config()

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
