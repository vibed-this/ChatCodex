# ChatCodex

## Architecture and security model

ChatCodex now uses an **OS-level full-access execution model**. There is no workspace sandbox and no approval gate used as the execution security boundary. The effective boundary is the operating-system account running ChatCodex.

Execution is split into transport-independent filesystem, search, shell, and patch capabilities behind `ExecutionService`. Runtime dependencies are composed during FastAPI lifespan startup rather than by an import-time singleton.

See [`SECURITY.md`](SECURITY.md) and [`docs/architecture.md`](docs/architecture.md) for the security and architecture models.

在 ChatGPT 中安全使用本机执行工具。

ChatCodex 是一个本地网关：它把你的 ChatGPT 对话连接到这台电脑上的本地执行服务，
让 ChatGPT 能执行命令、读写文件、搜索内容并应用补丁。
执行权限由运行 ChatCodex 的操作系统账户决定。

- **本地执行**：命令、文件读写、搜索与补丁直接由本机执行服务处理。
- **凭据分开**：登录控制台用的 Token 和 ChatGPT 连接用的密钥互不相同。

---

## 快速开始

只需要 Python 3.11+ 和 Node.js。

### 1. 启动网关

```bash
cd backend
uv sync --locked
uv run python -m app.main
```

首次启动会自动生成两个密钥并打印在控制台：

- **Web Access Token** — 用来登录下面的管理控制台。
- **MCP Access Token** — 留给 ChatGPT 连接用（见下文）。

> 没装 `uv`？也可以 `pip install fastapi uvicorn mcp websockets` 后用
> `python -m app.main` 启动；Windows 下直接运行 `backend/start.bat`。

### 2. 构建前端

```bash
cd frontend
npm install
npm run build
```

构建后网关会自动使用 `frontend/dist/` 里的界面；跳过这步也能跑，只是用内置的简化界面。

### 3. 打开控制台

浏览器访问 **http://127.0.0.1:8000/**，粘贴第 1 步打印的 **Web Access Token** 登录。

之后**几乎所有配置都在这个网页里改**，不用再去碰命令行参数。

---

## 让 ChatGPT 能连进来

网关默认只监听本机。要让 ChatGPT 访问，需要给它一个公网地址，两种方式任选：

| 方式 | 适合 | 怎么做 |
|---|---|---|
| **Cloudflare 隧道** | 大多数人 | 控制台 →「公网入口」→ 选 Cloudflare；临时域名调试、固定域名上线 |
| **直接暴露** | 已有公网 IP / 域名 | 把 HTTPS、证书、DNS 指向本机，控制台 →「公网入口」→ 选直接暴露 |

配好后，在 ChatGPT 里添加连接器：

1. 打开 `chatgpt.com` → **Settings → Connectors**。
2. URL 填 `<你的公网地址>/mcp/`（注意末尾斜杠）。
3. 按控制台「设置 → 访问与认证」里选的方式完成鉴权：
   - **OAuth**：浏览器会弹出授权页，输入你在控制台设置的 OAuth 密码。
   - **Token**：把 **MCP Access Token** 作为 Bearer 填入（不是 Web Access Token）。

> ChatGPT Tunnel 是控制台「设置」页里另一条独立的接入通道，不走上面的公网入口，
> 按需二选一或并用即可。

---

## 日常使用

- **开始一个任务**：在 ChatGPT 里让它打开工作区并直接调用本地执行工具。
- **管理上下文**：「执行上下文」页查看或归档每个对话绑定的工作区。

### 改动何时生效

- 公网入口、ChatGPT Tunnel：在对应页面即时启停。
- 认证类设置（Token / OAuth）：保存后需**重启网关**。
- 改了前端代码：重新 `npm run build` 并重启网关。

---

## 常见问题

**健康检查**：`curl http://127.0.0.1:8000/healthz`，返回 `{"ok":true,...}` 即正常。

**忘了 Web Access Token？** 重启网关会在控制台重新打印；也可在启动前用环境变量
`CHATCODEX_WEB_ACCESS_TOKEN` 指定一个固定值。

**登录控制台和连 ChatGPT 用的是同一个密钥吗？** 不是。Web Access Token 只用于登录控制台；
MCP Access Token / OAuth 才用于 ChatGPT 连接，两者独立、互不通用的。

**数据存在哪？** 默认在用户私有目录（Windows：`%LOCALAPPDATA%\ChatCodex\`；
Linux/macOS：`$XDG_STATE_HOME/chatcodex/`），可用 `CHATCODEX_DATABASE_URL` 更换位置。

---

## 进阶：环境变量

所有选项都能用环境变量在启动前覆盖；控制台改的配置优先级更高。常用的：

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHATCODEX_HOST` / `CHATCODEX_PORT` | `127.0.0.1:8000` | 监听地址 |
| `CHATCODEX_WEB_ACCESS_TOKEN` | 自动生成 | 控制台登录 Token |
| `CHATCODEX_MCP_ACCESS_TOKEN` | 自动生成 | ChatGPT 连接的静态密钥 |
| `CHATCODEX_MCP_AUTH_MODE` | `token` | `token` / `oauth` / `both` / `noauth` |
| `CHATCODEX_PUBLIC_URL` | `http://127.0.0.1:8000` | 公网地址（OAuth 需要） |
| `CHATCODEX_DATABASE_URL` | 用户私有目录 | 数据库位置（`sqlite:///` 或 `postgresql://`） |
| `CHATCODEX_CHROME_DEVTOOLS_MCP_ENABLED` | `1` | 启用 Chrome DevTools MCP 下游桥接；关闭可设为 `0` |
| `CHATCODEX_CHROME_DEVTOOLS_MCP_COMMAND` | `npx --yes chrome-devtools-mcp@latest` | Chrome DevTools MCP 启动命令 |

完整列表与默认值见控制台「设置」页。

## Chrome DevTools MCP

ChatCodex 可以把官方 `chrome-devtools-mcp` 的工具直接桥接到自己的 MCP 服务中。启用后，
下游工具会以 `chrome_` 前缀暴露，例如 `chrome_navigate_page`、`chrome_evaluate_script`、
`chrome_take_screenshot` 和 `chrome_list_pages`。

Chrome DevTools MCP 默认启用，但采用真正的按需启动：ChatCodex 自身启动以及 MCP 客户端的
`tools/list` 请求都不会拉起下游进程。Chrome 工具的名称和参数契约由本地 manifest 提供；只有客户端
实际调用 `chrome_*` 工具时，ChatCodex 才启动 `chrome-devtools-mcp` 并建立持久会话。
如不需要 Chrome DevTools MCP，可在控制台「设置」中关闭 `chrome_devtools_mcp_enabled`，或者设置
`CHATCODEX_CHROME_DEVTOOLS_MCP_ENABLED=0`。默认命令使用 `npx --yes`，首次使用时会由 npm 获取
`chrome-devtools-mcp`；也可以通过 `chrome_devtools_mcp_command` 指定自定义命令，
例如连接已有的调试 Chrome：`npx --yes chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222`。

Chrome DevTools MCP 在 ChatCodex MCP 生命周期内保持一个持久 stdio 会话，工具 schema 从下游
服务器动态发现并原样转发；ChatCodex 关闭时会同时关闭该下游会话。

[于 Linux.do 社区发布](https://linux.do)
