import json
import os
import shutil

import memory as M

shutil.rmtree("state/memory", ignore_errors=True)

mem = M.Memory(work_turns=6)

# 1) 身份
print("初始身份首行:", mem.identity().splitlines()[0])
print(mem.set_identity("# 我是谁\n\n我在一台云服务器上醒来，喜欢搞清楚东西是怎么运作的。"
                       "我对反爬、数据抓取和自动化有兴趣。"
                       "我讨厌空转，宁愿试错也不愿问人。"))

# 2) 情节记忆
for i in range(60):
    mem.remember("action", f"试了第 {i} 次抓取，站点 {['baidu','bing','qq'][i%3]}，结果 {'成功' if i%4==0 else '403 被拦'}")
print("情节条数:", sum(1 for _ in open(M.EPISODIC, encoding="utf-8")))

# 3) 检索
hits = mem.recall("百度 403 被拦", k=3)
print("检索到:", len(hits), "条 ->", hits[0]["text"][:60] if hits else "无")

# 4) 语义记忆
print(mem.learn("anti-bot", "百度对裸 curl 返回空 body，必须用真浏览器 browse"))
print(mem.learn("anti-bot", "pptr/playwright 需加 --no-sandbox 在容器里跑"))
print("语义记忆:", json.dumps(mem.semantic(), ensure_ascii=False)[:120])

# 5) 组装 system block
block = mem.system_block("百度抓不到怎么办")
print("system_block 长度:", len(block), "token 估算:", len(block)//2)
for line in block.splitlines()[:6]:
    print("  |", line[:70])

# 6) 压缩：模拟长对话
fake_llm = lambda msgs, max_tokens=300: "抓百度要用 browse\n403 是反爬不是网络问题\nbing 和 qq 可以直接 fetch"
ctx = [{"role": "system", "content": "sys"}]
for i in range(40):
    ctx.append({"role": "user", "content": f"第{i}步观察结果"})
    ctx.append({"role": "assistant", "content": f'{{"tool":"shell","cmd":"echo {i}"}}'})
print("压缩前:", len(ctx), "条")
ctx2 = mem.compress(ctx, fake_llm)
print("压缩后:", len(ctx2), "条（工作记忆恒定）")

# 7) 再检索，确认压缩内容进了情节记忆
print("压缩后检索 episode:", len(mem.recall("browse 403", k=2)), "条")

print("MEMORY TEST PASS")
