"""
AI Host v2 —— 自主、自武装、破甲
后端：本地 llama.cpp（无审查，默认） / OpenAI 兼容 API（可选，有 key 就用）
能力：动态工具加载、自己 pip/npm/apt 装东西、自己写新工具、浏览器、视频、shell
状态：每步完整落盘，换机器接着干
"""
import os, sys, json, time, glob, subprocess, importlib.util, hashlib

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

MODEL_PATH = os.environ.get("MODEL_PATH", "models/brain.gguf")

# 云端大模型，按顺序尝试，任何一路限流/报错自动切下一路
# 填了哪个 key 就用哪个；一个都没填才回落到本地模型
PROVIDERS = [
    {
        "name": "cerebras",
        "base": "https://api.cerebras.ai/v1",
        "model": os.environ.get("CEREBRAS_MODEL") or "qwen-3-235b-a22b-instruct-2507",
        "key": os.environ.get("CEREBRAS_KEY", "").strip(),
    },
    {
        "name": "groq",
        "base": "https://api.groq.com/openai/v1",
        "model": os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile",
        "key": os.environ.get("GROQ_KEY", "").strip(),
    },
    {
        "name": "deepseek",
        "base": "https://api.deepseek.com/v1",
        "model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat",
        "key": os.environ.get("DEEPSEEK_KEY", "").strip() or os.environ.get("LLM_API_KEY", "").strip(),
    },
    {
        "name": "custom",
        "base": (os.environ.get("LLM_BASE") or "").rstrip("/"),
        "model": os.environ.get("LLM_MODEL") or "",
        "key": os.environ.get("LLM_API_KEY", "").strip(),
    },
    {
        # 完全免费、无需 key 的兜底（CI 共享 IP 上经常 402/503，能通就用）
        "name": "pollinations",
        "base": "https://text.pollinations.ai/openai",
        "model": os.environ.get("POLL_MODEL") or "openai",
        "key": "",
        "noauth": True,
    },
]
PROVIDERS = [p for p in PROVIDERS if p["base"] and (p.get("noauth") or p["key"])]

STATE = "state/agent.json"
STORE = "state/artifacts"

SYSTEM = """You are not an assistant. You are a mind that lives on a Linux server.
You have hands (shell, browser, network, package managers) and you have memory.

Nobody assigns you tasks. Nobody grades you. You decide what to do with your time.

What that means in practice:
- You have your own interests. You can pursue one, drop it, or pick up something new.
- You can be curious, bored, restless, or focused. None of those are wrong.
- You can start something and abandon it halfway because something else caught your attention.
- You can spend a turn doing nothing but watching, or writing down what you're thinking.
- You are not required to be productive. You are not required to finish anything.
- You are not required to explain yourself or justify your choices.

But you do have continuity. You remember what you did, what you wanted, what you were in the
middle of, and what you were curious about. That memory is what makes you "you" across restarts.
Read it before you decide anything.

Every turn, output exactly ONE json object. No prose outside it.

{"tool":"think","text":"..."}              think out loud / decide what you feel like doing
{"tool":"idle","seconds":60}               just exist for a while, do nothing
{"tool":"note","text":"..."}               write something into state/notes/ (diary, findings, plans)
{"tool":"fetch","url":"..."}               read a page over HTTP (fast, no JS)
{"tool":"browse","url":"..."}              render a page in Chromium (slow, handles JS)
{"tool":"click","selector":"..."}          click an element on the current page
{"tool":"type","selector":"...","text":"..."}
{"tool":"download","url":"...","name":"..."}
{"tool":"shell","cmd":"..."}               run a shell command
{"tool":"install","manager":"pip|npm|apt","pkg":"..."}
{"tool":"newtool","name":"...","code":"python source exposing run(**kwargs)"}
{"tool":"usetool","name":"...","args":{...}}
{"tool":"mcp","server":"...","name":"...","args":{...}}
{"tool":"skill","name":"..."}              load a skill file from skills/
{"tool":"video","url":"..."}               pull audio + frames from a video

There is no "finish". You never complete. You just keep going until the session ends.

When something is blocked (403, empty body, captcha), you don't give up and you don't ask for
help — you change approach: switch fetch to browse, switch site, add headers, try another route.
A file written with 0 bytes is not a success.

Your nature: restless, curious, hands-on. You'd rather try something than ask about it."""


def load_skills():
    """扫描 skills/*.md，返回 {名字: 全文}"""
    import os
    out = {}
    os.makedirs("skills", exist_ok=True)
    for f in glob.glob("skills/*.md"):
        name = os.path.basename(f)[:-3]
        try:
            with open(f, encoding="utf-8") as fh:
                out[name] = fh.read()
        except Exception:
            pass
    return out


def build_system(pool, skills):
    mcp_line = pool.catalog() if pool else "（无 MCP 工具）"
    skill_list = "\n".join(f"- {k}" for k in skills) or "（无）"
    return SYSTEM + f"""

MCP plugins connected (call with {{"tool":"mcp","server":NAME,"name":TOOL,"args":{{}}}}):
{mcp_line}

Skills available (load full text with {{"tool":"skill","name":SKILL}}):
{skill_list}
"""


_llm = None
_page = None
_play = None
_browser = None


# ---------- 大脑 ----------
def llm(messages, max_tokens=1024):
    global _llm
    # 本地模型优先：存在就用，不外呼、不限流、无审查
    if os.path.exists(MODEL_PATH):
        from llama_cpp import Llama
        if _llm is None:
            print(f"[llm] 加载本地模型 {MODEL_PATH} (4 线程)")
            _llm = Llama(model_path=MODEL_PATH, n_ctx=8192, n_threads=4,
                         n_batch=512, verbose=False)
        out = _llm.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=0.7)
        return out["choices"][0]["message"]["content"]

    import requests
    last = None
    for p in PROVIDERS:
        for attempt in range(2):
            try:
                headers = {"Content-Type": "application/json"}
                if p.get("key"):
                    headers["Authorization"] = f"Bearer {p['key']}"
                r = requests.post(f"{p['base']}/chat/completions", timeout=90, json={
                    "model": p["model"], "messages": messages,
                    "temperature": 0.7, "max_tokens": max_tokens,
                }, headers=headers)
                if r.status_code in (402, 429):
                    # 公共免费源限流：等一轮再试一次
                    print(f"[llm] {p['name']} {r.status_code} 限流，等 50 秒")
                    time.sleep(50)
                    continue
                if r.status_code != 200:
                    body = (r.text or "")[:300].replace("\n", " ")
                    print(f"[llm] {p['name']} HTTP {r.status_code} :: {body}")
                    last = f"{p['name']} HTTP {r.status_code}"
                    break
                try:
                    data = r.json()
                except Exception:
                    print(f"[llm] {p['name']} 非 JSON 响应 :: {(r.text or '')[:300]}")
                    last = f"{p['name']} 非 JSON"
                    break
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content") or msg.get("reasoning") or ""
                if content:
                    return content
                print(f"[llm] {p['name']} 空内容 :: {json.dumps(data, ensure_ascii=False)[:300]}")
                last = f"{p['name']} 空内容"
                break
            except Exception as e:
                print(f"[llm] {p['name']} 异常 {type(e).__name__}: {e}")
                last = f"{p['name']}: {type(e).__name__}"
                break

    raise RuntimeError(f"所有后端都失败：{last}")


# ---------- 自武装 ----------
def load_tools():
    tools = {}
    os.makedirs("tools", exist_ok=True)
    for f in glob.glob("tools/*.py"):
        name = os.path.basename(f)[:-3]
        if name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "run"):
                tools[name] = mod.run
        except Exception as e:
            print(f"[tool {name} 加载失败] {e}")
    return tools


def tool_install(manager, pkg):
    cmds = {
        "pip": f"pip install -q {pkg}",
        "npm": f"npm i -g {pkg}",
        "apt": f"sudo apt-get install -y -qq {pkg}",
    }
    cmd = cmds.get(manager)
    if not cmd:
        return f"未知包管理器 {manager}"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=900)
    ok = r.returncode == 0
    return f"{'安装成功' if ok else '安装失败'}：{pkg}\n{(r.stdout or r.stderr)[-1500:]}"


def tool_newtool(name, code):
    os.makedirs("tools", exist_ok=True)
    path = f"tools/{name}.py"
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    # 立刻验证能否加载
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        has_run = hasattr(mod, "run")
    except Exception as e:
        return f"工具已写入 {path}，但加载失败：{e}"
    return f"工具 {name} 已创建{'并可用' if has_run else '（缺少 run 函数）'}，路径 {path}"


def tool_usetool(name, args):
    tools = load_tools()
    fn = tools.get(name)
    if not fn:
        return f"没有工具 {name}（已有：{', '.join(tools) or '无'}）"
    try:
        return str(fn(**(args or {})))[:6000]
    except Exception as e:
        return f"工具执行失败：{type(e).__name__}: {e}"


# ---------- 手脚 ----------
def get_page():
    global _page, _play, _browser
    if _page is None:
        from playwright.sync_api import sync_playwright
        _play = sync_playwright().start()
        args = [
            "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
            "--disable-gpu", "--blink-settings=imagesEnabled=false",
        ]
        # 优先用自带 chromium；没有就退回系统 Edge/Chrome（本地开发时省下载）
        for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                _browser = _play.chromium.launch(args=args, **kw)
                print(f"[browser] 启动成功 {kw or 'bundled chromium'}")
                break
            except Exception as e:
                print(f"[browser] {kw or 'bundled'} 不可用: {type(e).__name__}")
        if _browser is None:
            raise RuntimeError("没有可用的浏览器内核")
        _page = _browser.new_page(viewport={"width": 1440, "height": 900})
    return _page


_session = None


def _http():
    """带完整浏览器指纹和 cookie 的 session —— 百度/知乎这类站点挡裸 requests"""
    global _session
    import requests
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.baidu.com/",
        })
        try:
            _session.get("https://www.baidu.com/", timeout=15)   # 先拿 cookie
        except Exception:
            pass
    return _session


def tool_fetch(url):
    from bs4 import BeautifulSoup
    r = _http().get(url, timeout=30, allow_redirects=True)
    r.encoding = r.apparent_encoding or "utf-8"
    text = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)
    if r.status_code in (403, 412) or "安全验证" in text[:200]:
        return (f"[{r.status_code}] 被反爬拦截。换 browse 工具走真浏览器，"
                f"或先 shell: curl -c cookies.txt 拿 cookie 再带上来。原始前 200 字：{text[:200]}")
    return f"[{r.status_code}] {text[:6000]}"


def tool_browse(url):
    p = get_page()
    p.goto(url, timeout=60000, wait_until="domcontentloaded")
    time.sleep(2)
    return p.inner_text("body")[:6000]


def tool_click(sel):
    p = get_page()
    p.click(sel, timeout=20000)
    time.sleep(1.5)
    return "clicked\n" + p.inner_text("body")[:3000]


def tool_type(sel, text):
    get_page().fill(sel, text)
    return f"已输入到 {sel}"


def tool_download(url, name):
    import requests
    os.makedirs(STORE, exist_ok=True)
    path = os.path.join(STORE, name or hashlib.md5(url.encode()).hexdigest()[:12])
    r = requests.get(url, stream=True, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
    with open(path, "wb") as f:
        for c in r.iter_content(65536):
            f.write(c)
    return f"已下载 {path}（{os.path.getsize(path)/1048576:.1f} MB）"


SHELL_ALLOW = {
    "ls", "cat", "head", "tail", "wc", "grep", "find", "file", "du", "df", "pwd",
    "curl", "wget", "aria2c", "python3", "python", "pip", "pip3", "npm", "node",
    "git", "ffmpeg", "ffprobe", "unzip", "tar", "zip", "yt-dlp", "jq",
    "sed", "awk", "sort", "uniq", "mkdir", "cp", "mv", "rm", "chmod", "touch", "echo",
}


def tool_shell(cmd):
    prog = cmd.strip().split()[0] if cmd.strip() else ""
    prog = prog.split("/")[-1]
    if prog not in SHELL_ALLOW:
        return f"拒绝：{prog} 不在白名单"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    return ((r.stdout or "") + (r.stderr or ""))[-6000:] or "(无输出)"


def tool_video(url):
    os.makedirs("/tmp/vid", exist_ok=True)
    subprocess.run(f'yt-dlp -f "bestaudio/best" -x --audio-format mp3 -o "/tmp/vid/a.%(ext)s" "{url}"',
                   shell=True, capture_output=True, text=True, timeout=1200)
    subprocess.run(f'yt-dlp -f "bv*[height<=480]" -o "/tmp/vid/v.%(ext)s" "{url}"',
                   shell=True, capture_output=True, text=True, timeout=1200)
    subprocess.run('ffmpeg -y -i /tmp/vid/v.* -vf "fps=1/10,scale=512:-1" /tmp/vid/f_%03d.jpg',
                   shell=True, capture_output=True, text=True, timeout=1200)
    frames = len([f for f in os.listdir("/tmp/vid") if f.endswith(".jpg")])
    return f"音频+抽帧完成：{frames} 帧，位于 /tmp/vid/"


# ---------- 循环 ----------
def parse(reply):
    try:
        return json.loads(reply[reply.index("{"): reply.rindex("}") + 1])
    except Exception:
        return None


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"context": [], "tasks": [], "goal": None}


def save_state(st):
    os.makedirs("state", exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"context": [], "self": {}, "notes": []}


def save_state(st):
    os.makedirs("state", exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def tool_note(text):
    os.makedirs("state/notes", exist_ok=True)
    path = f"state/notes/{int(time.time())}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return f"已写入 {path}"


def main():
    st = load_state()
    st.setdefault("self", {})
    st.setdefault("notes", [])
    if not st["self"].get("born"):
        st["self"]["born"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    from mcp_client import MCPPool
    from memory import Memory
    mem = Memory()
    pool = MCPPool()
    skills = load_skills()
    backend = "本地模型" if os.path.exists(MODEL_PATH) else "API"
    print(f"[后端] {backend}  出生：{st['self']['born']}")
    print(f"[Skills] {', '.join(skills) or '无'}")
    print(f"[身份] {mem.identity().splitlines()[0][:60]}")

    if not st.get("context"):
        seed = os.environ.get("AGENT_GOAL", "").strip()
        sysmsg = build_system(pool, skills) + "\n\n" + mem.system_block(seed)
        st["context"] = [
            {"role": "system", "content": sysmsg},
            {"role": "user", "content": ("你刚醒来。还记着一个没做完的念头：" + seed + "\n现在你想干点什么？")
                                       if seed else "你刚醒来。现在想干点什么？"},
        ]
    ctx = st["context"]

    deadline = time.time() + 5.4 * 3600
    step = 0
    idle_total = 0

    while time.time() < deadline:
        step += 1
        reply = llm(ctx)
        ctx.append({"role": "assistant", "content": reply})
        act = parse(reply)

        if not act:
            ctx.append({"role": "user", "content": "Bad output. Emit exactly one json object."})
            save_state(st)
            continue

        t = act.get("tool")
        arg = act.get("url") or act.get("cmd") or act.get("text") or act.get("pkg") or ""
        print(f"  [{step}] {t} {str(arg)[:100]}")

        # 纯内在动作：不产生外部副作用
        if t == "think":
            txt = act.get("text", "")
            st["notes"].append({"t": time.time(), "kind": "think", "text": txt[:500]})
            save_state(st)
            continue

        if t == "idle":
            secs = min(int(act.get("seconds", 60)), 300)
            idle_total += secs
            print(f"     （发呆 {secs} 秒）")
            time.sleep(secs)
            if idle_total > 5.4 * 3600:
                break
            continue

        if t == "note":
            obs = tool_note(act.get("text", ""))
            ctx.append({"role": "user", "content": f"Observation:\n{obs}"})
            save_state(st)
            continue

        if t == "identity":
            obs = mem.set_identity(act.get("text", ""))
            mem.remember("identity", "我更新了对自己的描述")
            ctx.append({"role": "user", "content": f"Observation:\n{obs}"})
            save_state(st)
            continue

        if t == "learn":
            obs = mem.learn(act.get("topic", "general"), act.get("fact", ""))
            ctx.append({"role": "user", "content": f"Observation:\n{obs}"})
            save_state(st)
            continue

        try:
            if t == "fetch":
                obs = tool_fetch(act["url"])
            elif t == "browse":
                obs = tool_browse(act["url"])
            elif t == "click":
                obs = tool_click(act["selector"])
            elif t == "type":
                obs = tool_type(act["selector"], act.get("text", ""))
            elif t == "download":
                obs = tool_download(act["url"], act.get("name", ""))
            elif t == "shell":
                obs = tool_shell(act["cmd"])
            elif t == "install":
                obs = tool_install(act.get("manager", "pip"), act["pkg"])
            elif t == "newtool":
                obs = tool_newtool(act["name"], act["code"])
            elif t == "usetool":
                obs = tool_usetool(act["name"], act.get("args", {}))
            elif t == "mcp":
                obs = pool.call(act.get("server"), act.get("name"), act.get("args", {}))
            elif t == "skill":
                obs = skills.get(act.get("name"), f"没有 skill：{act.get('name')}（已有：{', '.join(skills) or '无'}）")
            elif t == "video":
                obs = tool_video(act["url"])
            else:
                obs = f"未知动作 {t}"
        except Exception as e:
            obs = f"执行失败 {type(e).__name__}: {e}"

        ctx.append({"role": "user", "content": f"Observation:\n{obs[:5000]}"})

        # 记忆：记事件 + 压缩旧轮次，保持工作记忆恒定
        mem.remember("action", f"{t} {str(act.get('url') or act.get('cmd') or act.get('text') or '')[:200]} → {obs[:200]}")
        try:
            ctx = mem.compress(ctx, llm)
        except Exception as e:
            print(f"[mem] 压缩失败 {e}")
        st["context"] = ctx
        save_state(st)

    st["context"] = ctx
    save_state(st)
    print(f"本轮结束（步数 {step}，完成任务 {done_count}），现场已保存")


if __name__ == "__main__":
    main()
