import os, yaml, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

OWNER = "wenfp108"
TOKEN = os.environ.get("GH_PAT", "")
HEADERS = {"Authorization": f"token {TOKEN}"} if TOKEN else {}
BJ = timezone(timedelta(hours=8))

def api(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params or {})
    if r.status_code in (404, 403):
        return None
    r.raise_for_status()
    return r.json()

def load_repos():
    repos = []
    for f in Path("repos").glob("*.yml"):
        with open(f) as fh:
            repos.append(yaml.safe_load(fh))
    return repos

def get_repo_stats(repo_name):
    """一次调用拿 last commit + 24h commits count + compare stats"""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    commits_url = f"https://api.github.com/repos/{OWNER}/{repo_name}/commits"

    # 获取最近的 commits（包含24h内）
    commits = api(commits_url, params={"since": since, "per_page": 100})
    if commits is None:
        return None

    count_24h = len(commits) if isinstance(commits, list) else 0

    # 获取最后一条 commit
    last = None
    adds, dels = 0, 0
    if isinstance(commits, list) and commits:
        c = commits[0]
        dt = datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
        last = {
            "time": dt.astimezone(BJ).strftime("%m-%d %H:%M"),
            "msg": c["commit"]["message"].split("\n")[0][:50],
        }

        # 用 compare API 一次性获取 24h 内的总变更量（比逐条查快得多）
        if count_24h > 0 and count_24h <= 250:
            oldest_sha = commits[-1]["sha"]
            newest_sha = commits[0]["sha"]
            if oldest_sha != newest_sha:
                compare = api(f"https://api.github.com/repos/{OWNER}/{repo_name}/compare/{oldest_sha}...{newest_sha}")
                if compare and "stats" in compare:
                    adds = compare["stats"].get("additions", 0)
                    dels = compare["stats"].get("deletions", 0)

    return {"last": last, "count": count_24h, "adds": adds, "dels": dels}

def get_workflow_stats(repo_name):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")
    url = f"https://api.github.com/repos/{OWNER}/{repo_name}/actions/runs"
    runs = api(url, params={"per_page": 20, "created": f">={since}"})
    if not runs or "workflow_runs" not in runs:
        return {}
    stats = {}
    for r in runs["workflow_runs"]:
        name = r["name"]
        if name not in stats:
            stats[name] = {"success": 0, "failure": 0, "other": 0}
        conclusion = r.get("conclusion")
        if conclusion == "success":
            stats[name]["success"] += 1
        elif conclusion == "failure":
            stats[name]["failure"] += 1
        else:
            stats[name]["other"] += 1
    return stats

def check_serv00(cfg):
    """通过 Central-Bank 的 reddit/sentiment/ 文件检测 serv00 状态"""
    if not TOKEN:
        return None
    repo = cfg.get("repo", "Central-Bank")
    label = cfg.get("label", "serv00")
    path = cfg.get("path", "reddit/sentiment")

    # 查最近修改 reddit/sentiment/ 的 commit
    commits = api(
        f"https://api.github.com/repos/{OWNER}/{repo}/commits",
        params={"path": path, "per_page": 1}
    )
    if not commits or not isinstance(commits, list) or not commits:
        return {"label": label, "status": "❓", "detail": "无法获取数据"}

    dt = datetime.fromisoformat(commits[0]["commit"]["author"]["date"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600

    if age_hours < 24:
        return {"label": label, "status": "🟢", "detail": f"最新数据 {dt.astimezone(BJ).strftime('%m-%d %H:%M')}"}
    elif age_hours < 72:
        return {"label": label, "status": "🟡", "detail": f"数据更新于 {dt.astimezone(BJ).strftime('%m-%d %H:%M')} ({int(age_hours)}h 前)"}
    else:
        return {"label": label, "status": "🔴", "detail": f"数据 {int(age_hours)}h 未更新"}

def generate():
    repos = load_repos()
    rows = []
    workflow_rows = []
    serv00_rows = []

    for repo in sorted(repos, key=lambda r: r["name"]):
        name = repo["name"]
        is_private = repo.get("private", False)
        tracks = repo.get("track", [])
        icon = "🔒" if is_private else "🌐"

        if is_private and not TOKEN:
            rows.append(f"| {icon} {name} | 🔐 | - | - | - |")
            continue

        stats = get_repo_stats(name)
        if stats is None:
            rows.append(f"| {icon} {name} | ❓ | N/A | - | - |")
            continue

        last_str = stats["last"]["time"] if stats["last"] else "N/A"
        count = stats["count"]
        change = f"+{stats['adds']}/-{stats['dels']}" if stats["adds"] or stats["dels"] else "-"
        status = "🟢" if count > 0 else "⚪"

        rows.append(f"| {icon} {name} | {status} | {last_str} | {count} | {change} |")

        if "workflow_runs" in tracks:
            wf = get_workflow_stats(name)
            for wf_name, s in wf.items():
                total = s["success"] + s["failure"] + s["other"]
                mark = "✅" if s["failure"] == 0 else "❌"
                workflow_rows.append(f"| {name} | {wf_name[:25]} | {mark} {s['success']}/{total} | {s['failure']} |")

        # serv00 状态检测
        if "serv00_check" in repo:
            result = check_serv00(repo["serv00_check"])
            if result:
                serv00_rows.append(result)

    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")

    md = f"""# 📊 wenfp108 仓库监控

> 更新：{now} BJT

| 仓库 | 状态 | 最后提交 | 24h提交 | 代码变更 |
|:-----|:-----|:---------|:--------|:---------|
"""
    for r in rows:
        md += r + "\n"

    if serv00_rows:
        md += """
## 服务器

| 服务 | 状态 | 详情 |
|:-----|:-----|:-----|
"""
        for s in serv00_rows:
            md += f"| {s['label']} | {s['status']} | {s['detail']} |\n"

    if workflow_rows:
        md += """
## CI (24h)

| 仓库 | Workflow | 成功率 | 失败 |
|:-----|:---------|:-------|:-----|
"""
        for w in workflow_rows:
            md += w + "\n"

    md += "\n---\n*by [refinery-monitor](https://github.com/wenfp108/refinery-monitor)*\n"
    Path("README.md").write_text(md, encoding="utf-8")
    print(f"✅ 监控 {len(repos)} 个仓库")

if __name__ == "__main__":
    generate()
