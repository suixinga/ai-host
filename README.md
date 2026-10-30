# ai-host —— 免费、能跑浏览器、能看视频的云端 Agent

跑在 GitHub Actions 上：**2 核 / 7G 内存 / 14G 磁盘 / Chromium / ffmpeg**，
public 仓库**不计分钟数**，每 15 分钟醒一次，状态完整落盘，接力不断线。

## 它到底能干什么

| 能力 | 怎么实现 |
|---|---|
| 上网、逛贴吧 | `fetch`（HTTP 抓取）/ `browse`（Chromium 渲染） |
| 点按钮、填表单 | `click` / `type` |
| 下软件、下文件 | `download` / `shell`（curl/aria2） |
| **看视频** | `video` 工具：yt-dlp 抽音频 + ffmpeg 抽帧，再交给大模型理解 |
| 装任何东西 | `shell`（apt/pip 都可，有白名单） |
| 24 小时不停 | 每个 job 跑 5 小时 50 分 → 派出接班 → 自己退出，零空窗 |

## 五步上线

1. **建仓库**：GitHub 新建一个 **public** 仓库（public 才不计分钟数），名字随意，比如 `ai-host`。
2. **推代码**：把这个目录推上去。
   ```
   git init && git add -A && git commit -m init
   git branch -M main
   git remote add origin https://github.com/你的用户名/ai-host.git
   git push -u origin main
   ```
3. **加大模型 key**：仓库 → Settings → Secrets and variables → Actions → New repository secret
   | Name | Value |
   |---|---|
   | `LLM_API_KEY` | 你的 DeepSeek key（或任何 OpenAI 兼容 key） |
   | `LLM_BASE` | `https://api.deepseek.com/v1` |
   | `LLM_MODEL` | `deepseek-chat` |
4. **手动跑一次**：Actions → ai-host → Run workflow。
5. **看结果**：跑完仓库里会多出 `state/agent.json`（记忆）和 `state/artifacts/`（产出）。

## 怎么给它派活

编辑 `state/agent.json` 里的 `tasks` 数组，加一条：

```json
{"id": 2, "goal": "打开 https://www.bilibili.com 搜索「显卡评测」，取前 5 个视频标题和链接", "done": false}
```

提交后下一轮（15 分钟内）自动接活。

## 存储与限制

| 项目 | 额度 |
|---|---|
| 热存储（job 内） | 14 GB，随 job 消失 |
| 永久存储（仓库） | 1 GB —— 只放状态和文本，别放二进制 |
| 流量 | **不限，不计费** |
| 单 job 寿命 | 6 小时（脚本在 5h24m 主动收尾） |
| 并发 | public 仓库 20 个 job |

大文件放 Cloudflare R2（10 GB 免费），不要塞进仓库。

## 为什么不是"投胎转世"

`state/agent.json` 里存的是**完整 context**（它自己说过的话、看到的观察、当前的计划），
不是外部日志。醒来第一件事是读回自己的记忆，接着上次的现场继续——
区别等于"睡着又醒"和"别人给你念日记"。
