"""极简 MCP server（stdio JSON-RPC），用于本地验证协议层。
不依赖 Node/npx，Windows 和 Linux 都能跑。
真实 MCP 插件（filesystem/fetch/sqlite）在 Ubuntu CI 上用 npx 启动。
"""
import sys, json

TOOLS = [
    {"name": "echo", "description": "回显输入文本",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "add", "description": "两数相加",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
]


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        if mid is None:
            continue  # notification
        if method == "initialize":
            res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "mock", "version": "1.0"}}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params", {})
            name = p.get("name")
            args = p.get("arguments", {})
            if name == "echo":
                out = f"echo:{args.get('text', '')}"
            elif name == "add":
                out = f"sum:{args.get('a', 0) + args.get('b', 0)}"
            else:
                out = f"unknown tool {name}"
            res = {"content": [{"type": "text", "text": out}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32601, "message": "method not found"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}), flush=True)


if __name__ == "__main__":
    main()
