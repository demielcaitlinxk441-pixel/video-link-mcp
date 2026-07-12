# 本机 HTTP MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 stdio MCP 的前提下，新增只监听本机回环地址的 Streamable HTTP MCP。

**Architecture:** `server.py` 使用同一个 FastMCP 实例及原有五个工具。新的命令行解析层把用户友好的 `--transport http` 映射为 SDK 的 `streamable-http`，并只允许修改端口；FastMCP 实例显式固定为 `127.0.0.1` 与 `/mcp`。Windows 启动脚本使用项目自身的虚拟环境。

**Tech Stack:** Python 3.10+、MCP Python SDK 1.28.1、FastMCP、unittest、Windows batch。

## Global Constraints

- `python server.py` 必须保持 stdio 行为。
- HTTP 地址必须为 `http://127.0.0.1:<port>/mcp`，禁止 `0.0.0.0`、局域网和公网监听。
- 默认端口为 `8000`，`--port` 仅可取 `1` 至 `65535`。
- 不修改五个 MCP 工具的名称、参数或返回格式。
- 不新增运行时依赖、认证、反向代理或云端部署。

---

### Task 1: 实现可测试的传输模式选择

**Files:**
- Modify: `server.py:31-44, 321-322`
- Create: `tests/test_http_mcp.py`

**Interfaces:**
- Produces: `RuntimeConfig(transport: str, port: int)`、`parse_runtime_config(argv: list[str] | None) -> RuntimeConfig`、`run_server(config: RuntimeConfig) -> None`。
- Consumes: `FastMCP.run(transport='stdio'|'streamable-http')` 和 `mcp.settings.model_copy`。

- [ ] **Step 1: Write the failing test**

```python
def test_http_mode_uses_streamable_http_and_localhost_port(self):
    config = server.parse_runtime_config(['--transport', 'http', '--port', '8765'])
    self.assertEqual(config.transport, 'streamable-http')
    self.assertEqual(config.port, 8765)
    with patch.object(server.mcp, 'run') as run:
        server.run_server(config)
    self.assertEqual(server.mcp.settings.host, '127.0.0.1')
    self.assertEqual(server.mcp.settings.port, 8765)
    run.assert_called_once_with(transport='streamable-http')
```

- [ ] **Step 2: Run the test and observe RED**

Run: `venv\Scripts\python.exe -m unittest tests.test_http_mcp.HttpMcpTests.test_http_mode_uses_streamable_http_and_localhost_port -v`

Expected: FAIL because the two functions do not exist.

- [ ] **Step 3: Implement the smallest runtime layer**

Add to `server.py` before the `FastMCP` instance:

```python
import argparse
from dataclasses import dataclass

LOCAL_HTTP_HOST = '127.0.0.1'
DEFAULT_HTTP_PORT = 8000

@dataclass(frozen=True)
class RuntimeConfig:
    transport: str
    port: int = DEFAULT_HTTP_PORT

def parse_runtime_config(argv: list[str] | None = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(description='Video Link Analyzer MCP Server')
    parser.add_argument('--transport', choices=('stdio', 'http'), default='stdio')
    parser.add_argument('--port', type=int, default=DEFAULT_HTTP_PORT)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    return RuntimeConfig('streamable-http' if args.transport == 'http' else 'stdio', args.port)

def run_server(config: RuntimeConfig) -> None:
    if config.transport == 'streamable-http':
        mcp.settings = mcp.settings.model_copy(update={'port': config.port})
    mcp.run(transport=config.transport)
```

Change `mcp = FastMCP('video-link-analyzer')` to `mcp = FastMCP('video-link-analyzer', host=LOCAL_HTTP_HOST, port=DEFAULT_HTTP_PORT)`. Replace the entry point with `run_server(parse_runtime_config())`.

- [ ] **Step 4: Run the focused test and observe GREEN**

Run: `venv\Scripts\python.exe -m unittest tests.test_http_mcp.HttpMcpTests.test_http_mode_uses_streamable_http_and_localhost_port -v`

Expected: PASS.

- [ ] **Step 5: Commit the tested feature**

Run: `git add server.py tests/test_http_mcp.py; git commit -m "feat: add local HTTP MCP transport"`

### Task 2: 保护现有 stdio 行为和端口边界

**Files:**
- Modify: `tests/test_http_mcp.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_runtime_config`。
- Produces: 默认行为与非法输入的回归覆盖。

- [ ] **Step 1: Write failing test cases**

```python
def test_default_mode_keeps_stdio_transport(self):
    config = server.parse_runtime_config([])
    self.assertEqual(config.transport, 'stdio')
    self.assertEqual(config.port, 8000)

def test_rejects_port_outside_valid_tcp_range(self):
    with self.assertRaises(SystemExit):
        server.parse_runtime_config(['--transport', 'http', '--port', '70000'])
```

- [ ] **Step 2: Run the invalid-port test and observe RED**

Run: `venv\Scripts\python.exe -m unittest tests.test_http_mcp.HttpMcpTests.test_rejects_port_outside_valid_tcp_range -v`

Expected: FAIL before the explicit range check is present.

- [ ] **Step 3: Add only the stated range validation**

Keep `if not 1 <= args.port <= 65535: parser.error('--port must be between 1 and 65535')` in `parse_runtime_config`; do not change any tool implementation.

- [ ] **Step 4: Run all HTTP unit tests**

Run: `venv\Scripts\python.exe -m unittest tests.test_http_mcp -v`

Expected: PASS for default stdio, custom HTTP port, fixed localhost host, and invalid port rejection.

- [ ] **Step 5: Commit the regression tests**

Run: `git add tests/test_http_mcp.py; git commit -m "test: cover HTTP MCP startup options"`

### Task 3: 提供可直接使用的 HTTP 配置和启动脚本

**Files:**
- Create: `scripts/start_http_mcp.bat`
- Create: `mcp_http_config_example.json`
- Modify: `README.md:86-121, 138-145`
- Modify: `setup.bat:62-73`
- Modify: `tests/test_repository_layout.py`
- Modify: `tests/test_setup_scripts.py`

**Interfaces:**
- Consumes: `server.py --transport http [--port <number>]`。
- Produces: `scripts\start_http_mcp.bat` 与 URL 为 `http://127.0.0.1:8000/mcp` 的客户端配置样例。

- [ ] **Step 1: Write the failing file-contract tests**

```python
def test_http_start_script_uses_project_virtual_environment(self):
    source = (ROOT / 'scripts' / 'start_http_mcp.bat').read_text(encoding='utf-8')
    self.assertIn('venv\\Scripts\\python.exe', source)
    self.assertIn('server.py" --transport http', source)

def test_http_example_uses_loopback_url(self):
    source = (ROOT / 'mcp_http_config_example.json').read_text(encoding='utf-8')
    self.assertIn('http://127.0.0.1:8000/mcp', source)
    self.assertNotIn('0.0.0.0', source)
```

- [ ] **Step 2: Run file-contract tests and observe RED**

Run: `venv\Scripts\python.exe -m unittest tests.test_repository_layout tests.test_setup_scripts -v`

Expected: FAIL because the HTTP script and configuration example do not exist.

- [ ] **Step 3: Add minimal user-facing assets**

Create `scripts/start_http_mcp.bat` with exactly this behavior:

```bat
@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
set "PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Run setup.bat first.
    exit /b 1
)
"%PYTHON%" "%PROJECT_DIR%\server.py" --transport http %*
```

Create `mcp_http_config_example.json`:

```json
{
  "mcpServers": {
    "video-link-analyzer-http": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Add an HTTP section to README: start `scripts\start_http_mcp.bat`, configure a compatible client with the URL above, use `scripts\start_http_mcp.bat --port 8765` for a port conflict, and explain that each user runs it on their own computer. Add files to the structure list. Add the same start command and URL to the end of `setup.bat` output.

- [ ] **Step 4: Run documentation/layout tests and observe GREEN**

Run: `venv\Scripts\python.exe -m unittest tests.test_repository_layout tests.test_setup_scripts -v`

Expected: PASS.

- [ ] **Step 5: Commit the documentation assets**

Run: `git add README.md setup.bat scripts/start_http_mcp.bat mcp_http_config_example.json tests/test_repository_layout.py tests/test_setup_scripts.py; git commit -m "docs: document local HTTP MCP usage"`

### Task 4: 验证实际 MCP HTTP 路由并完整回归

**Files:**
- Modify: `tests/test_http_mcp.py`
- Modify: `scripts/verify.py`

**Interfaces:**
- Consumes: `server.mcp.streamable_http_app()` 与本机 `/mcp` 路由。
- Produces: 离线 HTTP 合约检查和真实协议连通性验证。

- [ ] **Step 1: Write failing route-contract test**

```python
def test_streamable_http_app_exposes_mcp_route(self):
    app = server.mcp.streamable_http_app()
    paths = {route.path for route in app.routes}
    self.assertIn('/mcp', paths)
```

- [ ] **Step 2: Run test to establish behavior**

Run: `venv\Scripts\python.exe -m unittest tests.test_http_mcp.HttpMcpTests.test_streamable_http_app_exposes_mcp_route -v`

Expected: PASS after Task 1. If it passes before the test is added because the installed SDK supplies `/mcp`, preserve that result; Tasks 1–3 provide the red-green proof for new project behavior.

- [ ] **Step 3: Add the same assertion to the offline verifier**

Add `test_http_mcp_contract` in `scripts/verify.py`; it must import `server`, create `server.mcp.streamable_http_app()`, and assert that `/mcp` appears in its routes. Register it with the existing MCP import test.

- [ ] **Step 4: Run the full automated suite**

Run:

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -v
venv\Scripts\python.exe scripts\verify.py
venv\Scripts\python.exe diagnose.py
```

Expected: all unit tests pass, verifier exits `0`, diagnostics reports core readiness.

- [ ] **Step 5: Verify real localhost protocol connectivity**

Start `venv\Scripts\python.exe server.py --transport http --port 8765` in the background. Use the MCP Python Streamable HTTP client to initialize `http://127.0.0.1:8765/mcp` and list tools. Assert all names appear: `detect_link_type`, `get_video_info`, `download_video`, `extract_transcript`, `analyze_video`; then stop the process.

- [ ] **Step 6: Commit verification changes**

Run: `git add tests/test_http_mcp.py scripts/verify.py; git commit -m "test: verify local HTTP MCP endpoint"`

### Task 5: 推送已验证改动

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: clean `main` branch and `origin` remote.
- Produces: GitHub `main` 上的 HTTP MCP 升级。

- [ ] **Step 1: Confirm publication scope**

Run: `git status -sb; git log --oneline origin/main..HEAD; git diff --check origin/main...HEAD`

Expected: only HTTP MCP design, implementation, tests, documentation and configuration files are included.

- [ ] **Step 2: Push verified commits**

Run: `git push origin main`

Expected: push succeeds.

- [ ] **Step 3: Confirm synchronization**

Run: `git status -sb; git log --oneline -1 origin/main`

Expected: no ahead/behind marker and `origin/main` points at the latest HTTP MCP commit.
