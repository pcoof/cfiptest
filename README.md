# CF IP Tester

> Cloudflare 优选 IP 批量测试工具 · PyWebView 桌面应用

## 功能特性

- **批量解析**：支持 IPv4、IPv6（`[...]`括号）、域名，每行一条，格式 `地址:端口#备注`
- **延迟测试**：TCP 握手延迟（多次取均值，可配置）
- **下载测速**：通过 Cloudflare HTTPS 接口测速，单位 Mbps
- **地理信息**：国家 / 城市 / ISP / ASN（via ip-api.com）
- **运营商延迟**：电信 / 移动 / 联通 DNS 服务器连通性模拟
- **网络连通性**：可选检测 Cloudflare / Google / YouTube / GitHub / ChatGPT / Apple / Telegram
- **代理检测**：启动时自动检测环境变量代理、系统代理、TUN 网卡
- **排序 / 筛选**：延迟、下载、国家等多字段排序，实时搜索
- **导出**：EdgeTunnel 格式（`地址:端口#备注|国家|下载|延迟`），逐行输出，`|` 分隔字段

## 快速开始

```bat
# Windows
run.bat

# macOS / Linux
bash run.sh
```

或手动：

```bash
pip install pywebview
python main.py
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

# 优选订阅（sub:// 格式）
sub://sub.cmliussss.net#CM优选订阅
```

## 导出格式（EdgeTunnel）

```
1.2.3.4:443#备注|美国|12.3Mbps|45ms
[2606:4700::]:443#IPv6|日本|8.1Mbps|120ms
```

## 项目结构

```
cfiptest/
├── main.py          # 入口，pywebview 窗口
├── requirements.txt
├── run.bat          # Windows 一键启动
├── run.sh           # macOS/Linux 一键启动
└── app/
    ├── tester.py    # 后端测试引擎
    ├── api.py       # PyWebView JS-API bridge
    └── static/
        └── index.html  # 前端 UI
```

## 测试选项说明

| 选项 | 说明 | 默认 |
|------|------|------|
| 延迟 | TCP 握手延迟（ms） | ✓ |
| 国家 | 地理信息查询 | ✓ |
| 下载 | 下载速度测试 | ✓ |
| 运营商 | 电信/移动/联通延迟 | ✓ |
| DNS | DNS 解析测试 | - |
| 并发数 | 同时测试线程数 | 8 |
| Ping 次数 | 延迟测量次数 | 3 |
| 测速大小 | 下载文件大小 | 5MB |
