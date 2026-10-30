"""
最小 MCP (Model Context Protocol) 客户端 —— stdio JSON-RPC
让 Agent 能接任何现成的 MCP server（filesystem / github / sqlite / puppeteer / fetch ...）
"""
import json
import os
import shutil
import subprocess
import sys
import threading


def _resolve_cmd(cmd):
    """Windows 上 npx 实际是 npx.cmd —— .cmd/.bat 必须经 cmd.exe 转发，否则 WinError 22。"""
    if not cmd:
        return cmd
    exe = cmd[0]
    path = shutil.which(exe)
    if not path and sys.platform == "win32":
        for ext in (".cmd", ".exe", ".bat"):
            path = shutil.which(exe + ext)
            if path:
                break
    target = path or exe
    if sys.platform == "win32" and target.lower().endswith((".cmd", ".bat")):
        # 路径可能含空格（C:\Program Files\...），必须加引号交给 cmd
        return ["cmd", "/c", f'"{target}"'] + list(cmd[1:])
    return [target] + list(cmd[1:])


class MCPServer:
    def __init__(self, name, command, env=None):
        self.name = name
        self.command = command
        self.tools = []
        self._id = 0
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(
            _resolve_cmd(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env,
            shell=False,
        )
        self._init()

    def _send(self, method, params=None):
        with self._lock:
            self._id += 1
            mid = self._id
            msg = {"jsonrpc": "2.0", "id": mid, "method": method}
            if params is not None:
                msg["params"] = params
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except Exception:
                return None
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    return None
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                except Exception:
                    continue
                if resp.get("id") == mid:
                    if "error" in resp:
                        raise RuntimeError(f"{self.name}: {resp['error']}")
                    return resp.get("result")

    def _init(self):
        try:
            self._send("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-host", "version": "1.0"},
            })
            self.proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            self.proc.stdin.flush()
            r = self._send("tools/list", {})
            self.tools = (r or {}).get("tools", [])
        except Exception as e:
            print(f"[MCP {self.name} 初始化失败] {e}")
            self.tools = []

    def call(self, tool, args):
        r = self._send("tools/call", {"name": tool, "arguments": args or {}})
        if not r:
            return "(空响应)"
        parts = []
        for c in r.get("content", []):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        return "\n".join(parts)[:6000]

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


class MCPPool:
    def __init__(self, config_path="mcp.json"):
        self.servers = {}
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            return
        for name, spec in (cfg.get("servers") or {}).items():
            cmd = spec.get("command")
            if not cmd:
                continue
            try:
                s = MCPServer(name, cmd)
                if s.tools:
                    self.servers[name] = s
                    print(f"[MCP] {name} 已连接，工具 {len(s.tools)} 个")
            except Exception as e:
                print(f"[MCP] {name} 连接失败：{e}")

    def catalog(self):
        """给 LLM 看的工具清单"""
        lines = []
        for name, s in self.servers.items():
            for t in s.tools:
                lines.append(f"- mcp:{name}:{t['name']} — {(t.get('description') or '')[:90]}")
        return "\n".join(lines) or "（无 MCP 工具）"

    def call(self, server, tool, args):
        s = self.servers.get(server)
        if not s:
            return f"没有 MCP server {server}（已有：{', '.join(self.servers) or '无'}）"
        try:
            return s.call(tool, args)
        except Exception as e:
            return f"MCP 调用失败 {server}:{tool} — {e}"

    def close_all(self):
        for s in self.servers.values():
            s.close()
