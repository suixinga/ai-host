import json, os, sys, urllib.request, urllib.error

TOKEN = open(os.path.join(os.path.dirname(__file__), ".ght.txt"), encoding="utf-8").read().strip()
OWNER, REPO = "suixinga", "ai-host"


def api(path):
    r = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "check",
    })
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}


runs = api(f"/repos/{OWNER}/{REPO}/actions/runs?per_page=5")
print("=== 最近运行 ===")
for w in runs.get("workflow_runs", []):
    print(f"  #{w['id']}  {w['status']:<12} {str(w['conclusion']):<10} {w['created_at']}  {w['event']}")

if runs.get("workflow_runs"):
    latest = runs["workflow_runs"][0]
    jobs = api(f"/repos/{OWNER}/{REPO}/actions/runs/{latest['id']}/jobs")
    print("\n=== 最新一次步骤 ===")
    for j in jobs.get("jobs", []):
        print(f"  job {j['name']}: {j['status']} / {j['conclusion']}")
        for s in j.get("steps", []):
            print(f"    {s['number']:>2}. {s['name']:<50} {s['conclusion'] or s['status']}")

print("\n=== 仓库文件（state/） ===")
tree = api(f"/repos/{OWNER}/{REPO}/git/trees/main?recursive=1")
for t in tree.get("tree", []):
    if t["path"].startswith("state") or t["path"].startswith("tools"):
        print(f"  {t['path']}  ({t.get('size', 0)} bytes)")

print("\n=== 记忆状态 ===")
st = api(f"/repos/{OWNER}/{REPO}/contents/state/agent.json")
if "content" in st:
    import base64
    d = json.loads(base64.b64decode(st["content"]).decode())
    print("  tasks:", [(t.get("id"), t.get("done"), str(t.get("result"))[:60]) for t in d.get("tasks", [])])
    print("  context 条数:", len(d.get("context", [])))

print("\n=== artifacts 目录 ===")
art = api(f"/repos/{OWNER}/{REPO}/contents/state/artifacts")
if isinstance(art, list):
    for a in art:
        print(f"  {a['name']}  {a.get('size',0)} bytes")
else:
    print("  ", art.get("error") or "空")
