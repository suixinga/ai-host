# 抓网页（含百度系）

## 铁律
**百度系（贴吧/知道/搜索）对裸 HTTP 请求返回空 body 或滑块验证。curl / fetch 会拿到 0 字节，不要用。**

## 正确做法
| 目标 | 用什么 |
|---|---|
| 百度贴吧、百度搜索 | **browse**（真 Chromium 渲染） |
| Bing、腾讯新闻、知乎、微博 | fetch 通常可以，抓不到就 browse |
| 需要登录 / 无限滚动 / 点按钮 | browse + click + type |

## 判断成功
- 抓回来长度 < 200 字 → 大概率被拦，换 browse 重试
- 看到「安全验证」「滑块」「请完成验证」→ 被反爬，换站或换 browse
- **写进文件前先检查内容非空**，别把 0 字节当成功

## 示例：用 browse 抓 Bing 搜索结果
```python
{"tool": "browse", "url": "https://www.bing.com/search?q=%E6%98%BE%E5%8D%A1"}
```
拿到文本后，用 shell 提取标题行写文件：
```bash
python3 -c "
import re,sys
t=open('/tmp/x.txt').read()
print('\n'.join(re.findall(r'^.{5,60}$', t, re.M)[:10]))
" > state/artifacts/titles.txt
```

## 产出规范
- 结果统一写到 `state/artifacts/<名字>.txt`
- **写完用 shell 检查** `wc -c state/artifacts/*.txt`，0 字节就是失败，要重试
