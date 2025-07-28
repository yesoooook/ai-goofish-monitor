# 闲鱼监控机器人

一个基于 Playwright 的闲鱼多任务实时监控工具，配备了功能完善的 Web 管理界面。

## ✨ 项目亮点

- **可视化Web界面**: 提供完整的Web UI，支持任务的可视化管理、运行日志实时查看和结果筛选浏览，无需直接操作命令行和配置文件。
- **多任务并发**: 通过 `config.json` 同时监控多个关键词，各任务独立运行，互不干扰。
- **实时流式处理**: 发现新商品后，立即进行处理，告别批处理延迟。
- **高度可定制**: 每个监控任务均可配置独立的关键词、价格范围和筛选条件。
- **健壮的反爬策略**: 模拟真人操作，包含多种随机延迟和用户行为，提高稳定性。

## 页面截图
后台任务管理
![img.png](img.png)

后台监控截图
![img_1.png](img_1.png)

## 🚀 快速开始 (Web UI 推荐)

推荐使用 Web 管理界面来操作本项目，体验最佳。

### 第 1 步: 环境准备

克隆本项目到本地:
```bash
git clone https://github.com/dingyufei615/ai-goofish-monitor
cd ai-goofish-monitor
```

安装所需的Python依赖：
```bash
pip install -r requirements.txt
```

### 第 2 步: 基础配置

1.  **配置环境变量**: 在项目根目录创建一个 `.env` 文件，并填入以下配置信息。
    ```env
    # ntfy 通知服务配置
    NTFY_TOPIC_URL="https://ntfy.sh/your-topic-name" # 替换为你的 ntfy 主题 URL

    # 企业微信机器人通知配置
    WX_BOT_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"

    # 是否使用edge 默认使用chrome
    LOGIN_IS_EDGE=false

    # 是否开启电脑链接转换为手机链接
    PCURL_TO_MOBILE=true

    # 爬虫是否以无头模式运行 (true/false)。遇到滑动验证码时，可设为 false
    RUN_HEADLESS=true
    ```

2.  **获取登录状态 (重要!)**: 为了让爬虫能够以登录状态访问闲鱼，**必须先运行一次登录脚本**以生成会话状态文件。
    ```bash
    python login.py
    ```
    运行后会弹出一个浏览器窗口，请使用**手机闲鱼App扫描二维码**完成登录。成功后，程序会自动关闭，并在项目根目录生成一个 `xianyu_state.json` 文件。

### 第 3 步: 启动 Web 服务

一切就绪后，启动 Web 管理后台服务器。
```bash
python web_server.py
```

### 第 4 步: 开始使用

在浏览器中打开 `http://127.0.0.1:8000` 访问管理后台。

1.  在 **“任务管理”** 页面，点击 **“创建新任务”**。
2.  在弹出的窗口中，填写任务名称、关键词等信息。
3.  回到主界面，点击右上角的 **“🚀 全部启动”**，开始享受自动化监控！

## 📸 Web UI 功能一览

-   **任务管理**:
    -   **可视化编辑**: 在表格中直接修改任务参数，如关键词、价格范围等。
    -   **启停控制**: 独立控制每个任务的启用/禁用状态，或一键启停所有任务。
-   **结果查看**:
    -   **卡片式浏览**: 以图文卡片形式清晰展示每个符合条件的商品。
    -   **深度详情**: 查看每个商品的完整抓取数据。
-   **运行日志**:
    -   **实时日志流**: 在网页上实时查看爬虫运行的详细日志，方便追踪进度和排查问题。
-   **系统设置**:
    -   **状态检查**: 一键检查登录状态等关键依赖是否正常。

## ⚙️ 命令行高级用法

对于喜欢命令行的用户，项目同样保留了脚本独立运行的能力。

### 启动监控

直接运行主爬虫脚本，它会加载 `config.json` 中所有启用的任务。
```bash
python spider_v2.py
```
**调试模式**: 如果只想测试少量商品，可以使用 `--debug-limit` 参数。
```bash
# 每个任务只处理前2个新发现的商品
python spider_v2.py --debug-limit 2
```

## 🚀 工作流程

```mermaid
graph TD
    A[启动主程序] --> B{读取 config.json};
    B --> C{并发启动多个监控任务};
    C --> D[任务: 搜索商品];
    D --> E{发现新商品?};
    E -- 是 --> F[抓取商品详情 & 卖家信息];
    F --> G[下载商品图片];
    G --> H[发送 ntfy 通知];
    H --> K[保存记录到 JSONL];
    E -- 否 --> L[翻页/等待];
    L --> D;
    K --> E;
```

## 🛠️ 技术栈

- **核心框架**: Playwright (异步) + asyncio
- **Web服务**: FastAPI
- **通知服务**: ntfy
- **配置管理**: JSON
- **依赖管理**: pip

## 📂 项目结构

```
.
├── .env                # 环境变量，存放API密钥等敏感信息
├── .gitignore          # Git忽略配置
├── config.json         # 核心配置文件，用于定义所有监控任务
├── login.py            # 首次运行必须执行，用于获取并保存登录Cookie
├── spider_v2.py        # 核心爬虫程序
├── web_server.py       # Web服务主程序
├── requirements.txt    # Python依赖库
├── README.md           # 就是你正在看的这个文件
├── static/             # Web前端静态文件
│   ├── css/style.css
│   └── js/main.js
├── templates/          # Web前端模板
│   └── index.html
├── images/             # (自动创建) 存放下载的商品图片
├── logs/               # (自动创建) 存放运行日志
└── *.jsonl             # (自动创建) 存放每个任务的抓取和分析结果
```

## 致谢

本项目在开发过程中参考了以下优秀项目，特此感谢：
- [superboyyy/xianyu_spider](https://github.com/superboyyy/xianyu_spider)

以及感谢LinuxDo相关佬友的脚本贡献
- [@jooooody](https://linux.do/u/jooooody/summary)

## ⚠️ 注意事项

- 请遵守闲鱼的用户协议和robots.txt规则，不要进行过于频繁的请求，以免对服务器造成负担或导致账号被限制。
- 本项目仅供学习和技术研究使用，请勿用于非法用途。
