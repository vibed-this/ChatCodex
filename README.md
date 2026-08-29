# ChatCodex

## Architecture and security model

ChatCodex now uses an **OS-level full-access execution model**. There is no workspace sandbox and no approval gate used as the execution security boundary. The effective boundary is the operating-system account running ChatCodex.

Execution is split into transport-independent filesystem, search, shell, and patch capabilities behind `ExecutionService`. Runtime dependencies are composed during FastAPI lifespan startup rather than by an import-time singleton.

For command execution, `bash` is synchronous and blocking. Use `shell_spawn` for long-running or resident work; it returns immediately and redirects stdout/stderr directly to a temporary file. Use `shell_wait` to wait for completion (optionally with a timeout) and `shell_kill` to terminate a background shell. Read background command output from the returned `outputPath` with the normal `read` or `grep` tools. When several background commands are independent, use `batch_call` to spawn them first and then wait for them.

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

也可以在启动命令中直接指定认证配置；命令行参数优先于环境变量和数据库中的已保存配置：

```bash
uv run python -m app.main --web-token WEB_TOKEN --mcp-auth-mode both --mcp-token MCP_TOKEN --oauth-token OAUTH_TOKEN
```

可用参数：

- `--web-token` / `--web-access-token`：设置 Web 控制台 Access Token。
- `--mcp-auth-mode`：设置 MCP 认证方式，支持 `token`、`oauth`、`both`、`noauth`。
- `--mcp-token` / `--mcp-access-token`：设置 MCP 静态 Bearer Token。
- `--oauth-token`：设置 OAuth Bearer Token；未显式指定 `--mcp-auth-mode` 时，会自动确保 MCP 接受 OAuth Token。

这些命令行凭据只覆盖当前 Gateway 进程，不会写回数据库配置。

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
| **直接暴露** | 已有公网 IP / 域名 | 把 HTTPS、证书、DNS 指向本机，控制台 →「公网入口」→ 选直接暴露 |

配好后，在 ChatGPT 里添加连接器：

1. 打开 `chatgpt.com` → **Settings → Connectors**。
2. URL 填 `<你的公网地址>/mcp/`（注意末尾斜杠）。
3. 按控制台「设置 → 访问与认证」里选的方式完成鉴权：
   - **OAuth**：浏览器会弹出授权页，输入你在控制台设置的 OAuth 密码。
   - **Token**：把 **MCP Access Token** 作为 Bearer 填入（不是 Web Access Token）。

> 按需二选一或并用即可。

---

## 日常使用

- **开始一个任务**：在 ChatGPT 里让它打开工作区并直接调用本地执行工具。

### 改动何时生效

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

完整列表与默认值见控制台「设置」页。

[于 Linux.do 社区发布](https://linux.do)

## External MCP federation

ChatCodex can connect to user-configured external MCP servers and expose their tools through the same `/mcp/` endpoint as native ChatCodex tools. Supported transports are **stdio**, **SSE**, and **Streamable HTTP**. Each external tool is namespaced as `server__tool` to avoid collisions while preserving the upstream input/output schema.

External MCP servers are configured from the Web console under **External MCP**. The configuration is stored in the local Gateway database, connections are established on demand, and active sessions are closed with the Gateway. HTTP headers and stdio environment values are masked when returned to the console; unchanged masked values are preserved on save.

For stdio servers, configure a command, argument array, optional working directory, and environment variables. For SSE or Streamable HTTP, configure the server URL and optional HTTP headers. The **Test connection** action performs a real MCP initialization and tool discovery without adding the temporary connection to the Gateway.

The Gateway continues to expose native tools and federated external tools together. External connection failures are isolated: an unavailable external server does not prevent native ChatCodex tools from being listed.
