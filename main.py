#!/usr/bin/env python3
"""
CF IP Tester - Main entry point
Usage: python main.py
"""
import os
import sys
import pathlib

# 添加项目根目录到 path
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import webview
from app.api import Api


def create_window():
    api = Api()

    html_path = ROOT / "app" / "static" / "index.html"
    # Windows 下转换为 file:/// URI 避免路径解析问题
    html_uri = html_path.as_uri()

    window = webview.create_window(
        title="CF IP Tester",
        url=html_uri,
        js_api=api,
        width=1280,
        height=780,
        min_size=(900, 600),
        background_color="#0f1117",
        frameless=False,
        easy_drag=False,
        text_select=True,
    )

    api.set_window(window)
    return window


def main():
    window = create_window()
    webview.start(
        debug="--debug" in sys.argv or os.environ.get("CFIPTEST_DEBUG") == "1",
        private_mode=True,   # 禁用缓存，确保每次加载最新 HTML
    )


if __name__ == "__main__":
    main()
