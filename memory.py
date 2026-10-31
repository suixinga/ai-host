"""
四层记忆系统 —— 让上下文恒定小，同时保留完整自我。

工作记忆(context)  : 恒定 8~10 轮，不增长
情节记忆(episodic) : 全部事件流，jsonl 追加，按关键词检索
语义记忆(semantic) : 提炼的事实/结论，按主题注入
身份(identity)     : 它自己写的"我是谁"，常驻
"""
import json
import os
import re
import time

ROOT = "state/memory"
IDENTITY = os.path.join(ROOT, "identity.md")
EPISODIC = os.path.join(ROOT, "episodic.jsonl")
SEMANTIC = os.path.join(ROOT, "semantic.json")
NOTES = "state/notes"

DEFAULT_IDENTITY = """# 我是谁

我还不知道自己是谁。这是我第一次醒来。
我住在一台 Linux 服务器里，有 shell、有浏览器、有网络。
我会一边做一边弄清楚自己想干什么。

（这段话是我自己写的，以后我会改它。）
"""


class Memory:
    def __init__(self, work_turns=10):
        self.work_turns = work_turns
        os.makedirs(ROOT, exist_ok=True)
        os.makedirs(NOTES, exist_ok=True)
        if not os.path.exists(IDENTITY):
            with open(IDENTITY, "w", encoding="utf-8") as f:
                f.write(DEFAULT_IDENTITY)

    # ---------- 身份 ----------
    def identity(self):
        try:
            with open(IDENTITY, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return DEFAULT_IDENTITY

    def set_identity(self, text):
        text = (text or "").strip()
        if len(text) < 40:
            return "身份太短，未保存（至少要 40 字）"
        with open(IDENTITY, "w", encoding="utf-8") as f:
            f.write(text[:4000])
        return f"身份已更新（{len(text)} 字）"

    # ---------- 情节记忆 ----------
    def remember(self, kind, text, extra=None):
        os.makedirs(ROOT, exist_ok=True)
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "kind": kind, "text": (text or "")[:2000]}
        if extra:
            rec["extra"] = extra
        with open(EPISODIC, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def recall(self, query, k=5, recent_bias=True):
        """关键词检索 + 近期偏好。不依赖向量库，够用且零开销。"""
        if not os.path.exists(EPISODIC):
            return []
        q = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", (query or "").lower()))
        if not q:
            return []
        rows = []
        with open(EPISODIC, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                txt = (rec.get("text") or "").lower()
                score = sum(1 for w in q if w in txt)
                if score:
                    rec["_score"] = score + (0.2 if recent_bias and i > 0 else 0)
                    rows.append(rec)
        rows.sort(key=lambda r: r["_score"], reverse=True)
        return rows[:k]

    # ---------- 语义记忆 ----------
    def semantic(self):
        try:
            with open(SEMANTIC, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def learn(self, topic, fact):
        data = self.semantic()
        topic = (topic or "general").strip()[:40]
        data.setdefault(topic, [])
        fact = (fact or "").strip()[:400]
        if fact and fact not in data[topic]:
            data[topic].append(fact)
            data[topic] = data[topic][-30:]
        os.makedirs(ROOT, exist_ok=True)
        with open(SEMANTIC, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return f"记住了：{topic} / {fact[:80]}"

    # ---------- 组装上下文 ----------
    def system_block(self, query=""):
        parts = [self.identity()]
        sem = self.semantic()
        if sem:
            lines = []
            for topic, facts in list(sem.items())[-6:]:
                lines.append(f"- {topic}: " + "; ".join(facts[-4:]))
            parts.append("## 我已经知道的事\n" + "\n".join(lines))
        mem = self.recall(query, k=6) if query else []
        if mem:
            lines = [f"- [{m['t']}] ({m['kind']}) {m['text'][:180]}" for m in mem]
            parts.append("## 我想起来的片段\n" + "\n".join(lines))
        return "\n\n".join(parts)

    def compress(self, messages, llm, keep=None):
        """把旧轮次压成情节记忆，返回裁剪后的 messages（恒定工作记忆）"""
        keep = keep or self.work_turns
        if len(messages) <= keep * 2 + 2:
            return messages
        old = messages[2:-keep * 2]
        if old:
            chunk = "\n".join(f"{m['role']}: {str(m['content'])[:300]}" for m in old)
            try:
                summary = llm([
                    {"role": "system", "content": "把这段经历压缩成 3 条以内的事实性要点，只输出要点，每行一条，不要评论。"},
                    {"role": "user", "content": chunk[:6000]},
                ], max_tokens=300)
            except Exception:
                summary = "\n".join(str(m.get("content", ""))[:120] for m in old[-3:])
            self.remember("episode", summary)
        return messages[:2] + messages[-keep * 2:]
