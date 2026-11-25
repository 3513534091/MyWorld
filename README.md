# MyWorld

本地跑一个服务，浏览器打开就是一个工作台 —— 类似 ComfyUI 的那种形态：**前端只负责界面与交互，后端负责内容与任务**，两者通过 REST + WebSocket 通信。

当前是 **v0.1.0 骨架版**：端口管理、静态前端、REST 状态接口、WebSocket 心跳/重连/服务端广播链路都已打通，节点画布留在下一步。

![MyWorld 界面](docs/screenshot.png)

## 快速开始

```powershell
# Windows
.\run.ps1                 # 默认 http://127.0.0.1:8000
.\run.ps1 --port 9000     # 换端口
.\run.ps1 --port 9000 --open   # 启动后自动打开浏览器
```

```bash
# Linux / macOS / Git Bash
./run.sh --port 9000
```

也可以直接用模块方式启动：

```powershell
python -m myworld --port 9000
```

依赖（FastAPI / uvicorn / websockets）：

```powershell
python -m pip install -r requirements.txt   # 或 pip install -e .
```

## 端口与配置

优先级从高到低：**命令行参数 → 环境变量 `MYWORLD_*` → 配置文件 `myworld.config.json` → 内置默认值**。

| 方式 | 写法 | 说明 |
|---|---|---|
| 命令行 | `--port 9000` | 最直接 |
| 环境变量 | `$env:MYWORLD_PORT = 9000` | 适合脚本/IDE 里固定 |
| 配置文件 | 复制 `myworld.config.example.json` 为 `myworld.config.json` | 适合长期项目配置 |

字段：`host`（默认 `127.0.0.1`，只允许本机访问）、`port`（默认 `8000`）、`open_browser`、`log_level`。

端口行为：

- 端口被占用时**自动向上找一个空闲端口**，启动 banner 会写明「8000 被占用，已顺延到 8001」，前端「运行状态」里也显示「端口来源」。
- 加 `--strict-port` 则改为直接报错退出，适合 CI 或需要固定端口的场景。
- 想让局域网其他设备访问，用 `--host 0.0.0.0`（注意：无鉴权，仅限可信网络）。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 版本、端口、运行时长、PID、请求数、WS 连接数 |
| GET | `/api/config` | 生效配置 + **每个字段的来源**（cli / env / file / default） |
| GET | `/api/events` | 事件总线订阅者数量 |
| POST | `/api/demo/tick` | 向所有已连接页面广播一条事件（验证推送链路） |
| GET | `/api/docs` | 自动生成的 Swagger 文档 |
| WS | `/ws` | 心跳与事件推送通道 |

WebSocket 协议（全部是 JSON）：

```jsonc
// 服务端 → 客户端，连接建立时
{ "kind": "hello", "version": "0.1.0", "port": 8000, "pid": 1234, "uptime_seconds": 1.2 }

// 客户端 → 服务端，心跳
{ "type": "ping", "t": 1712345678901 }
// 回应
{ "kind": "pong", "t": 1712345678901, "server_time": 1712345678.9 }

// 客户端 → 服务端，让所有页面收到一条广播
{ "type": "broadcast", "payload": { "hello": "world" } }

// 客户端 → 服务端，拉一次完整状态
{ "type": "stats" }
```

## 目录结构

```
myworld/
  __init__.py        版本号
  __main__.py        命令行入口（参数解析、banner、启动 uvicorn）
  config.py          配置解析：优先级合并、端口校验与自动顺延
  events.py          进程内事件总线（发布 → 多个 WS 订阅者）
  server.py          FastAPI 应用：REST + WebSocket + 静态托管
web/
  index.html         界面结构
  css/style.css      深色主题
  js/app.js          状态渲染、WS 连接/心跳/重连、日志面板
tests/
  test_config.py     配置解析单元测试（纯标准库）
  smoke_test.py      端到端冒烟测试（真实进程 + REST + WS）
run.ps1 / run.sh     启动脚本
myworld.config.example.json
```

## 测试

```powershell
python tests/test_config.py     # 配置与端口逻辑
python tests/smoke_test.py      # 起真实服务，跑 HTTP + WebSocket 全链路
```

## 下一步

- [ ] 节点画布：可拖拽、可连线的图编辑器（LiteGraph 或自研 canvas）
- [ ] 节点定义与后端执行队列（提交任务 → WS 推送进度）
- [ ] 任务历史与结果预览
- [ ] 前端构建化（需要组件复用和多页面时再引入 Vite，目前零构建即开即用）
