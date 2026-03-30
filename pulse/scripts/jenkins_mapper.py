"""READ-ONLY scan: Map Jenkins jobs to GitHub repos by reading build metadata."""
import json, sys, urllib.request, base64, ssl

JENKINS_URL = "https://jenkins.webmotors.com.br"
AUTH = "andre.nascimento@webmotors.com.br:1122e51c75a720b4b9445ca2ac3518e171"

TARGET_REPOS = {
    "webmotors-private/webmotors.next.ui",
    "webmotors-private/webmotors.portal.ui",
    "webmotors-private/webmotors.buyer.ui",
    "webmotors-private/webmotors.buyer.desktop.ui",
    "webmotors-private/webmotors.catalogo.next.ui",
    "webmotors-private/webmotors.fipe.next.ui",
    "webmotors-private/webmotors.pf",
    "webmotors-private/eleanor.flutter",
    "webmotors-private/webmotors.app.pf.search.bff",
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

b64auth = base64.b64encode(AUTH.encode()).decode()

def fetch_json(url):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {b64auth}")
    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def normalize_repo(git_url):
    url = git_url.lower().replace(".git", "")
    if "github.com:" in url:
        return url.split("github.com:")[-1]
    if "github.com/" in url:
        parts = url.split("github.com/")[-1]
        segments = parts.strip("/").split("/")
        if len(segments) >= 2:
            return f"{segments[0]}/{segments[1]}"
    return url

# Get all jobs
job_list = fetch_json(f"{JENKINS_URL}/api/json?tree=jobs[fullName,color]")
all_jobs = job_list.get("jobs", [])

active = [
    j for j in all_jobs
    if j.get("color") not in (None, "disabled", "notbuilt")
    and "Folder" not in j.get("_class", "")
    and "MultiBranch" not in j.get("_class", "")
]

print(f"Scanning {len(active)} jobs (READ-ONLY)...", file=sys.stderr)

repo_to_jobs = {}
scanned = 0

for job in active:
    name = job["fullName"]
    color = job.get("color", "?")
    
    # Handle nested folder paths
    path_parts = name.split("/")
    encoded_path = "/job/".join(urllib.request.quote(p, safe="") for p in path_parts)
    url = f"{JENKINS_URL}/job/{encoded_path}/lastBuild/api/json"
    
    build_data = fetch_json(url)
    scanned += 1
    
    if scanned % 200 == 0:
        print(f"  ...{scanned}/{len(active)}", file=sys.stderr)
    
    if not build_data:
        continue
    
    result = build_data.get("result", "?")
    
    for action in build_data.get("actions", []):
        if action is None:
            continue
        if action.get("_class") == "hudson.plugins.git.util.BuildData":
            for remote_url in action.get("remoteUrls", []):
                repo = normalize_repo(remote_url)
                if repo in TARGET_REPOS:
                    if repo not in repo_to_jobs:
                        repo_to_jobs[repo] = []
                    # Avoid duplicates
                    if not any(j["job"] == name for j in repo_to_jobs[repo]):
                        repo_to_jobs[repo].append({
                            "job": name,
                            "color": color,
                            "last_result": result,
                        })

print(f"Done! Scanned {scanned}/{len(active)}", file=sys.stderr)
print(json.dumps(repo_to_jobs, indent=2))
