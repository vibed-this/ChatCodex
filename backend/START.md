# ChatCodex 启动指南(零参数)

## 一键启动

```bash
cd backend
pip install fastapi uvicorn mcp websockets   # 只一次
start.bat          # Windows
# 或 bash start.sh
```

**不用 set 任何参数。** 首次启动会分别生成 Web Access Token 和 MCP Access Token,持久化后打印在控制台。

## 启动后

- **管理面板**:`http://127.0.0.1:8000/` — **所有配置都在这里改**
- MCP:`http://127.0.0.1:8000/mcp/`(带斜杠)
- 健康:`http://127.0.0.1:8000/healthz`

## 全部配置都在 Web 面板(不再用环境变量)

| 面板位置 | 配置项(原环境变量) |
|---|---|
| **设置 → 访问与认证** | Web/MCP Token、OAuth 密码、回调保护、`PUBLIC_URL` |
| **设置 → 会话默认** | 默认 Subagent 模型、Subagent 能力、历史模式、审批策略、沙箱 |

> 两个 Token 自动生成后会**分别持久化**,重启复用。面板只显示“已配置”,可轮换但不会回显秘密；首次值见启动输出。

## 接 ChatGPT

2. ChatGPT → Settings → Connectors → URL 填 `<公网URL>/mcp/`
3. 鉴权:
   - **OAuth / Both**:ChatGPT 弹授权页,输入面板设置的 OAuth 密码；OAuth issuer 必须通过全局公网入口的稳定 HTTPS URL 可达。Secure Tunnel 只改写 MCP resource，不转发授权服务器
   - Web Access Token 只登录管理控制台,绝不能填到 MCP 客户端

## 改动生效

- **认证**:保存后需重启 Gateway。
- **前端**:改 frontend 后 `npm run build` 再重启。

## 验证

```bash
curl http://127.0.0.1:8000/healthz
# {"ok":true,"healthy":true,...}
```
