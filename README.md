# CF IP Tester

> Cloudflare 优选 IP 批量测试工具 · PyWebView 桌面应用

## 功能特性

- **批量解析**：支持 IPv4、IPv6（`[...]`括号）、域名，每行一条，格式 `地址:端口#备注`
- **延迟测试**：TCP 握手延迟（多次取均值，可配置）
- **下载测速**：通过 Cloudflare HTTPS 接口测速，单位 Mbps
- **地理信息**：国家 / 城市 / ISP / ASN（via ip-api.com）
- **运营商延迟**：电信 / 移动 / 联通 DNS 服务器连通性模拟
- **网络连通性**：可选检测 Cloudflare / Google / YouTube / GitHub / ChatGPT / Apple / Telegram
- **代理检测**：启动时自动检测环境变量代理、系统代理、PAC、TUN 网卡；检测到代理时禁用测试并提示关闭
- **排序 / 筛选**：延迟、下载、国家等多字段排序，实时搜索
- **导出**：EdgeTunnel 格式（`地址:端口#备注|国家|下载|延迟`），逐行输出，`|` 分隔字段

## 环境要求

- Python >= 3.13.5
- [uv](https://docs.astral.sh/uv/)（推荐）

## 快速开始

使用 [uv](https://docs.astral.sh/uv/) 管理依赖：

```bash
# 同步依赖
uv sync

# 启动应用
uv run python main.py
```

或者使用标准 Python：

```bash
pip install pywebview>=6.2.1
python main.py
```

## 打包为单文件 EXE

```bash
uv run pyinstaller --onefile --windowed --noconsole --name cfiptest --add-data "app/static;app/static" main.py
```

## 地址格式

```
# 标准格式
1.2.3.4:443#我的IP
[2606:4700::]:2053#IPv6示例
www.visa.cn#CF优选域名

# 省略端口（默认443）
www.cloudflare.com#CF

# API 链接（直接输入 URL 后点「加载 URL」）
https://raw.githubusercontent.com/cmliu/WorkerVless2sub/main/addressesapi.txt
```

## 导出格式（EdgeTunnel）

```
1.2.3.4:443#备注|美国|12.3Mbps|45ms
[2606:4700::]:443#IPv6|日本|8.1Mbps|120ms
```

## 项目结构

```
cfiptest/
├── main.py                    # 入口，pywebview 窗口
├── pyproject.toml             # uv / Python 项目配置
├── uv.lock                    # uv 锁定文件
├── README.md
├── .github/
│   └── workflows/
│       └── build.yml          # GitHub Actions 云端构建 EXE
└── app/
    ├── tester.py              # 后端测试引擎
    ├── api.py                 # PyWebView JS-API bridge
    └── static/
        ├── css/style.css      # 前端样式
        └── index.html         # 前端 UI
```

## GitHub Actions 自动构建

每次 push 到 `main` / `master` 分支时，GitHub Actions 会在 Windows 云端运行 `pyinstaller` 构建 `cfiptest.exe`，并上传 Artifact 供下载。也可在 Actions 页面手动触发。

## 测试选项说明

| 选项 | 说明 | 默认 |
|------|------|------|
| 延迟 | TCP 握手延迟（ms） | ✓ |
| 国家 | 地理信息查询 | ✓ |
| 下载 | 下载速度测试 | ✓ |
| 运营商 | 电信/移动/联通延迟 | ✓ |
| 城市 | 城市信息 | - |
| ASN | 自治系统号 | - |
| 并发数 | 同时测试线程数 | 8 |
| Ping 次数 | 延迟测量次数 | 3 |
| 测速大小 | 下载文件大小 | 5MB |
