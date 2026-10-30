# 逛贴吧并提取帖子列表

## 何时用
任务涉及百度贴吧（tieba.baidu.com）的列表、帖子标题、搜索。

## 打法
1. 贴吧是服务端渲染，**不需要浏览器**，用 fetch 就够：
   - 吧首页：`https://tieba.baidu.com/f?kw=<吧名>`（中文要 URL 编码）
   - 搜索：`https://tieba.baidu.com/f/search/res?qw=<关键词>`
2. 帖子标题在 `a.j_th_tit` 里。用 shell 跑一段解析：

```bash
python3 - <<'PY'
import requests, urllib.parse
from bs4 import BeautifulSoup
kw = urllib.parse.quote("显卡")
r = requests.get(f"https://tieba.baidu.com/f?kw={kw}",
                 headers={"User-Agent":"Mozilla/5.0"}, timeout=20)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.text, "lxml")
for a in soup.select("a.j_th_tit")[:10]:
    print(a.get_text(strip=True), "https://tieba.baidu.com" + a.get("href",""))
PY
```

3. 需要翻页就加 `&pn=50`（第二页）、`&pn=100`（第三页）。
4. 需要登录才能看的（回复、私信），才升级到 browse + 手动登录态。

## 注意
- 频率别太快，连续请求加 `sleep 2`，否则会跳验证页。
- 结果统一写到 `state/artifacts/`，不要塞进 context。
