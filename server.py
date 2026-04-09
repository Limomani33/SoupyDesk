"""
SoupyDesk 2.0 — server.py
Full OS backend: user management, GitHub sync, FS API, SSearch proxy
"""
import os, json, hashlib, base64, uuid, time, threading, re
from aiohttp import web, ClientSession, ClientTimeout
import requests as req_lib

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
APPS_DIR  = os.path.join(BASE_DIR, "apps")
FS_FILE   = os.path.join(BASE_DIR, "filesystem.json")

# ── GitHub config ─────────────────────────────────────────────────────────────
GH_TOKEN  = os.environ.get("GH_TOKEN", "")
GH_REPO   = os.environ.get("GH_REPO", "")       # e.g. "you/soupydesk-users"
GH_BRANCH = os.environ.get("GH_BRANCH", "main")
def GH_API():
    return f"https://api.github.com/repos/{GH_REPO}"

def gh_headers():
    return {"Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"}

def gh_get_file(path):
    """Get a file from GitHub repo. Returns (content_str, sha) or (None, None)."""
    try:
        r = req_lib.get(f"{GH_API()}/contents/{path}",
                        headers=gh_headers(), timeout=10)
        if r.status_code == 200:
            d = r.json()
            content = base64.b64decode(d["content"]).decode("utf-8")
            return content, d["sha"]
        return None, None
    except:
        return None, None

def gh_put_file(path, content_str, message="SoupyDesk sync", sha=None):
    """Create or update a file on GitHub."""
    if not GH_TOKEN or not GH_REPO:
        return False
    try:
        body = {
            "message": message,
            "content": base64.b64encode(content_str.encode()).decode(),
            "branch": GH_BRANCH
        }
        if sha:
            body["sha"] = sha
        r = req_lib.put(f"{GH_API()}/contents/{path}",
                        headers=gh_headers(), json=body, timeout=15)
        return r.status_code in (200, 201)
    except:
        return False

def gh_delete_file(path, sha, message="SoupyDesk delete"):
    if not GH_TOKEN or not GH_REPO:
        return False
    try:
        body = {"message": message, "sha": sha, "branch": GH_BRANCH}
        r = req_lib.delete(f"{GH_API()}/contents/{path}",
                           headers=gh_headers(), json=body, timeout=10)
        return r.status_code == 200
    except:
        return False

def gh_list_dir(path):
    """List files in a GitHub directory."""
    try:
        r = req_lib.get(f"{GH_API()}/contents/{path}",
                        headers=gh_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()  # list of file objects
        return []
    except:
        return []

# ── Password hashing ──────────────────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ── In-memory filesystem (local, per-session) ─────────────────────────────────
SYSTEM_STRUCTURE = {
    "__type": "dir", "__meta": {"icon": "folder-system", "protected": True},
    "Main": {
        "__type": "dir", "__meta": {"icon": "folder-main", "protected": True},
        "SystemApps": {
            "__type": "dir", "__meta": {"icon": "folder-apps", "protected": True},
            "SShell.app":         {"__type":"app","__meta":{"protected":True,"desc":"Terminal"}},
            "SSearch.app":        {"__type":"app","__meta":{"protected":True,"desc":"Browser"}},
            "Files.app":          {"__type":"app","__meta":{"protected":True,"desc":"File Explorer"}},
            "ControlCenter.app":  {"__type":"app","__meta":{"protected":True,"desc":"Settings"}},
            "TaskManager.app":    {"__type":"app","__meta":{"protected":True,"desc":"Task Manager"}},
            "SessionManager.app": {"__type":"app","__meta":{"protected":True,"desc":"User Accounts"}},
            "ValueEditor.app":    {"__type":"app","__meta":{"protected":True,"desc":"Registry Editor"}},
            "SoupyChat.app":      {"__type":"app","__meta":{"protected":True,"desc":"SoupyChat"}},
        }
    },
    "Users": {
        "__type": "dir", "__meta": {"icon": "folder-users", "protected": True}
    }
}

def build_user_structure(username):
    """Build a fresh user folder structure."""
    default_settings = {
        "theme": "soapycore2",
        "wallpaper": None,
        "cursor": "default",
        "customCursor": None,
        "icon_folder": None,
        "icon_html": None,
        "icon_error": None,
        "dock_position": "bottom",
        "show_clock": True,
        "show_battery": False,
        "animations": True,
        "font_size": "medium",
        "language": "en",
        "timezone": "auto",
        "start_menu_style": "grid"
    }
    default_pinned = [
        {"name":"Files","icon":"📁","type":"app"},
        {"name":"SoupyChat","icon":"💬","type":"app"},
        {"name":"SSearch","icon":"🌐","type":"app"},
        {"name":"SShell","icon":"🖥️","type":"app"},
        {"name":"ControlCenter","icon":"⚙️","type":"app"},
    ]
    default_values = {
        "System.MaxRecentFiles": 10,
        "System.AnimationSpeed": 1.0,
        "Desktop.GridSize": 88,
        "Shell.HistorySize": 100,
        "Search.DefaultEngine": "google",
        "Window.DefaultWidth": 700,
        "Window.DefaultHeight": 500,
        "User.DisplayName": username,
    }
    return {
        "__type": "dir", "__meta": {"icon": "folder-user", "protected": False},
        "Desktop":   {"__type":"dir","__meta":{"icon":"folder","protected":False}},
        "Documents": {"__type":"dir","__meta":{"icon":"folder-doc","protected":False}},
        "Downloads": {"__type":"dir","__meta":{"icon":"folder-dl","protected":False}},
        "Music":     {"__type":"dir","__meta":{"icon":"folder-music","protected":False}},
        "USRCONFIG": {
            "__type":"dir","__meta":{"icon":"folder-cfg","protected":False},
            "UserInfo.json": {
                "__type":"file",
                "__content": base64.b64encode(json.dumps({
                    "username": username,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }).encode()).decode(),
                "__mime":"application/json","__meta":{}
            }
        },
        "Settings.SDConfig": {
            "__type":"file",
            "__content": base64.b64encode(json.dumps(default_settings, indent=2).encode()).decode(),
            "__mime":"application/json","__meta":{}
        },
        "PinnedApps.SDConfig": {
            "__type":"file",
            "__content": base64.b64encode(json.dumps(default_pinned, indent=2).encode()).decode(),
            "__mime":"application/json","__meta":{}
        },
        "Values.SDVC": {
            "__type":"file",
            "__content": base64.b64encode(json.dumps(default_values, indent=2).encode()).decode(),
            "__mime":"application/json","__meta":{}
        }
    }

def load_fs():
    if os.path.exists(FS_FILE):
        try:
            with open(FS_FILE) as f:
                return json.load(f)
        except:
            pass
    fs = {"System": json.loads(json.dumps(SYSTEM_STRUCTURE))}
    save_fs(fs)
    return fs

def save_fs(fs):
    with open(FS_FILE, "w") as f:
        json.dump(fs, f, indent=2)

fs_data = load_fs()
fs_lock = threading.Lock()

# ── Sessions ──────────────────────────────────────────────────────────────────
sessions = {}  # token -> {username, logged_in_at}

def create_session(username):
    token = str(uuid.uuid4())
    sessions[token] = {"username": username, "created": time.time()}
    return token

def get_session(request):
    token = request.headers.get("X-SD-Token") or request.rel_url.query.get("token")
    if token and token in sessions:
        return sessions[token]
    return None

# ── FS helpers ────────────────────────────────────────────────────────────────
def parse_path(path):
    return [p for p in path.strip("/").split("/") if p]

def get_node(fs, parts):
    node = fs
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node

def set_node(fs, parts, value):
    node = fs
    for p in parts[:-1]:
        if p not in node:
            node[p] = {"__type":"dir","__meta":{}}
        node = node[p]
    node[parts[-1]] = value

def del_node(fs, parts):
    node = fs
    for p in parts[:-1]:
        node = node[p]
    if parts[-1] in node:
        del node[parts[-1]]

def get_user_path_prefix(username):
    return ["System", "Users", username]

# ── GitHub sync ───────────────────────────────────────────────────────────────
def sync_user_to_github(username):
    """Push a user's folder to GitHub asynchronously."""
    if not GH_TOKEN or not GH_REPO:
        print(f"[GitHub] Skipping sync for {username}: GH_TOKEN or GH_REPO not set")
        return
    def _sync():
        try:
            with fs_lock:
                user_node = get_node(fs_data, ["System", "Users", username])
            if not user_node:
                print(f"[GitHub] No user node found for {username}")
                return
            # Strip auth hash before pushing (security)
            import copy
            safe_node = copy.deepcopy(user_node)
            if "USRCONFIG" in safe_node and "auth.json" in safe_node["USRCONFIG"]:
                safe_node["USRCONFIG"]["auth.json"]["__meta"] = {"hidden": True}
            content = json.dumps(safe_node, indent=2)
            path = f"Users/{username}/data.json"
            existing, sha = gh_get_file(path)
            ok = gh_put_file(path, content, f"Sync user {username}", sha)
            print(f"[GitHub] Sync {username}: {'OK' if ok else 'FAILED'}")
        except Exception as e:
            print(f"[GitHub] Sync error for {username}: {e}")
    threading.Thread(target=_sync, daemon=True).start()

def sync_user_from_github(username):
    """Pull user data from GitHub and merge into local FS."""
    if not GH_TOKEN or not GH_REPO:
        return False
    content, _ = gh_get_file(f"Users/{username}/data.json")
    if not content:
        return False
    try:
        user_data = json.loads(content)
        with fs_lock:
            if "System" not in fs_data:
                fs_data["System"] = json.loads(json.dumps(SYSTEM_STRUCTURE))
            if "Users" not in fs_data["System"]:
                fs_data["System"]["Users"] = {"__type":"dir","__meta":{"icon":"folder-users","protected":True}}
            fs_data["System"]["Users"][username] = user_data
            save_fs(fs_data)
        return True
    except:
        return False

def get_all_github_users():
    """List all users stored on GitHub."""
    items = gh_list_dir("Users")
    if not isinstance(items, list):
        return []
    return [i["name"] for i in items if i.get("type") == "dir"]

# ── AUTH ROUTES ───────────────────────────────────────────────────────────────
async def auth_signup(request):
    body = await request.json()
    username = body.get("username","").strip()
    password = body.get("password","")
    if not username or not password:
        return web.json_response({"ok":False,"error":"Username and password required"})
    if len(username) < 2 or not re.match(r'^[a-zA-Z0-9_\-]+$', username):
        return web.json_response({"ok":False,"error":"Username must be 2+ alphanumeric chars"})
    if len(password) < 4:
        return web.json_response({"ok":False,"error":"Password must be 4+ characters"})

    # Check if user exists locally
    with fs_lock:
        users_node = get_node(fs_data, ["System","Users"])
        if username in (users_node or {}):
            return web.json_response({"ok":False,"error":"Username already taken"})

    # Check GitHub too
    existing, _ = gh_get_file(f"Users/{username}/data.json")
    if existing:
        return web.json_response({"ok":False,"error":"Username already taken"})

    # Create user
    pw_hash = hash_pw(password)
    user_struct = build_user_structure(username)
    # Store hash in USRCONFIG
    user_struct["USRCONFIG"]["auth.json"] = {
        "__type":"file",
        "__content": base64.b64encode(json.dumps({"username":username,"pw_hash":pw_hash}).encode()).decode(),
        "__mime":"application/json","__meta":{"hidden":True}
    }

    with fs_lock:
        if "System" not in fs_data:
            fs_data["System"] = json.loads(json.dumps(SYSTEM_STRUCTURE))
        if "Users" not in fs_data["System"]:
            fs_data["System"]["Users"] = {"__type":"dir","__meta":{"icon":"folder-users","protected":True}}
        fs_data["System"]["Users"][username] = user_struct
        save_fs(fs_data)

    # Push to GitHub
    sync_user_to_github(username)

    token = create_session(username)
    return web.json_response({"ok":True,"token":token,"username":username})

async def auth_login(request):
    body = await request.json()
    username = body.get("username","").strip()
    password = body.get("password","")
    pw_hash  = hash_pw(password)

    # Check local first
    with fs_lock:
        user_node = get_node(fs_data, ["System","Users",username])

    if not user_node:
        # Try pulling from GitHub
        pulled = sync_user_from_github(username)
        if not pulled:
            return web.json_response({"ok":False,"error":"User not found"})
        with fs_lock:
            user_node = get_node(fs_data, ["System","Users",username])

    if not user_node:
        return web.json_response({"ok":False,"error":"User not found"})

    # Verify password
    auth_node = get_node(user_node, ["USRCONFIG","auth.json"])
    if not auth_node:
        return web.json_response({"ok":False,"error":"Auth data missing"})
    try:
        auth_data = json.loads(base64.b64decode(auth_node["__content"]).decode())
        if auth_data.get("pw_hash") != pw_hash:
            return web.json_response({"ok":False,"error":"Incorrect password"})
    except:
        return web.json_response({"ok":False,"error":"Auth error"})

    token = create_session(username)
    return web.json_response({"ok":True,"token":token,"username":username})

async def auth_check_user(request):
    """Check if a username exists (for other-user folder access prompt)."""
    body = await request.json()
    username = body.get("username","").strip()
    password = body.get("password","")
    pw_hash  = hash_pw(password)

    with fs_lock:
        user_node = get_node(fs_data, ["System","Users",username])
    if not user_node:
        sync_user_from_github(username)
        with fs_lock:
            user_node = get_node(fs_data, ["System","Users",username])
    if not user_node:
        return web.json_response({"ok":False,"error":"User not found"})

    auth_node = get_node(user_node, ["USRCONFIG","auth.json"])
    try:
        auth_data = json.loads(base64.b64decode(auth_node["__content"]).decode())
        if auth_data.get("pw_hash") == pw_hash:
            return web.json_response({"ok":True})
    except:
        pass
    return web.json_response({"ok":False,"error":"Incorrect password"})

async def auth_list_users(request):
    """List all local users (names only)."""
    with fs_lock:
        users = {k:v for k,v in (get_node(fs_data,["System","Users"]) or {}).items() if not k.startswith("__")}
    return web.json_response({"users": list(users.keys())})

async def auth_logout(request):
    token = (await request.json()).get("token","")
    sessions.pop(token, None)
    return web.json_response({"ok":True})

async def auth_change_password(request):
    sess = get_session(request)
    if not sess:
        return web.json_response({"ok":False,"error":"Not logged in"}, status=401)
    body = await request.json()
    old_pw = body.get("old_password","")
    new_pw = body.get("new_password","")
    username = sess["username"]

    with fs_lock:
        auth_node = get_node(fs_data, ["System","Users",username,"USRCONFIG","auth.json"])
    if not auth_node:
        return web.json_response({"ok":False,"error":"Auth data missing"})
    try:
        auth_data = json.loads(base64.b64decode(auth_node["__content"]).decode())
        if auth_data.get("pw_hash") != hash_pw(old_pw):
            return web.json_response({"ok":False,"error":"Wrong current password"})
    except:
        return web.json_response({"ok":False,"error":"Auth error"})

    new_hash = hash_pw(new_pw)
    new_auth = json.dumps({"username":username,"pw_hash":new_hash})
    with fs_lock:
        auth_node["__content"] = base64.b64encode(new_auth.encode()).decode()
        save_fs(fs_data)
    sync_user_to_github(username)
    return web.json_response({"ok":True})

# ── FS ROUTES ─────────────────────────────────────────────────────────────────
def resolve_user_path(sess, path):
    """
    Paths starting with ~ are relative to user's home.
    /System/Users/OtherUser requires auth check.
    """
    parts = parse_path(path)
    return parts

async def fs_list(request):
    sess  = get_session(request)
    path  = request.rel_url.query.get("path", "/")
    parts = parse_path(path)

    with fs_lock:
        node = get_node(fs_data, parts) if parts else fs_data
    if node is None:
        return web.json_response({"error":"not found"}, status=404)

    items = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("__"): continue
            if isinstance(v, dict):
                t    = v.get("__type","dir")
                meta = v.get("__meta",{})
                # Hide auth.json from listing
                if k == "auth.json" and meta.get("hidden"): continue
                items.append({
                    "name":k,"type":t,
                    "icon":meta.get("icon","folder"),
                    "protected":meta.get("protected",False),
                    "desc":meta.get("desc",""),
                    "size":len(v.get("__content","")) if t=="file" else None
                })
    items.sort(key=lambda x:(x["type"]!="dir", x["name"].lower()))
    return web.json_response({"path":path,"items":items})

async def fs_read(request):
    path  = request.rel_url.query.get("path","")
    parts = parse_path(path)
    with fs_lock:
        node = get_node(fs_data, parts)
    if node is None:
        return web.json_response({"error":"not found"}, status=404)
    return web.json_response({"content":node.get("__content",""),"mime":node.get("__mime","text/plain")})

async def fs_write(request):
    sess = get_session(request)
    body = await request.json()
    path = body.get("path","")
    content = body.get("content","")
    mime = body.get("mime","text/plain")
    meta = body.get("meta",{})
    parts = parse_path(path)
    if not parts:
        return web.json_response({"error":"invalid path"}, status=400)
    with fs_lock:
        node = fs_data
        for p in parts[:-1]:
            if p not in node:
                node[p] = {"__type":"dir","__meta":{}}
            node = node[p]
        node[parts[-1]] = {"__type":"file","__content":content,"__mime":mime,"__meta":meta}
        save_fs(fs_data)
    if sess:
        sync_user_to_github(sess["username"])
    return web.json_response({"ok":True})

async def fs_mkdir(request):
    sess = get_session(request)
    body = await request.json()
    path = body.get("path","")
    parts = parse_path(path)
    with fs_lock:
        node = fs_data
        for p in parts:
            if p not in node:
                node[p] = {"__type":"dir","__meta":{}}
            node = node[p]
        save_fs(fs_data)
    if sess:
        sync_user_to_github(sess["username"])
    return web.json_response({"ok":True})

async def fs_delete(request):
    sess  = get_session(request)
    body  = await request.json()
    path  = body.get("path","")
    force = body.get("force", False)
    parts = parse_path(path)
    with fs_lock:
        node = get_node(fs_data, parts)
    if node is None:
        return web.json_response({"error":"not found"}, status=404)
    protected = node.get("__meta",{}).get("protected",False) if isinstance(node,dict) else False
    if protected and not force:
        return web.json_response({"error":"protected","message":"System file. Use force=true."}, status=403)
    with fs_lock:
        del_node(fs_data, parts)
        save_fs(fs_data)
    if sess:
        sync_user_to_github(sess["username"])
    return web.json_response({"ok":True, "was_protected": protected})

async def fs_move(request):
    sess = get_session(request)
    body = await request.json()
    src  = parse_path(body.get("src",""))
    dst  = parse_path(body.get("dst",""))
    with fs_lock:
        node = get_node(fs_data, src)
        if node is None:
            return web.json_response({"error":"src not found"}, status=404)
        set_node(fs_data, dst, node)
        del_node(fs_data, src)
        save_fs(fs_data)
    if sess:
        sync_user_to_github(sess["username"])
    return web.json_response({"ok":True})

async def fs_upload(request):
    sess   = get_session(request)
    reader = await request.multipart()
    dest   = "/"
    uploaded = []
    while True:
        field = await reader.next()
        if field is None: break
        if field.name == "dest":
            dest = await field.text()
        elif field.name == "file":
            filename = field.filename or f"file_{uuid.uuid4().hex[:6]}"
            data     = await field.read()
            mime     = field.headers.get("Content-Type","application/octet-stream")
            b64      = base64.b64encode(data).decode()
            parts    = parse_path(dest) + [filename]
            with fs_lock:
                node = fs_data
                for p in parts[:-1]:
                    if p not in node:
                        node[p] = {"__type":"dir","__meta":{}}
                    node = node[p]
                node[parts[-1]] = {"__type":"file","__content":b64,"__mime":mime,"__meta":{}}
            uploaded.append(filename)
    with fs_lock:
        save_fs(fs_data)
    if sess:
        sync_user_to_github(sess["username"])
    return web.json_response({"ok":True,"uploaded":uploaded})

async def fs_reset(request):
    global fs_data
    fs_data = {"System": json.loads(json.dumps(SYSTEM_STRUCTURE))}
    save_fs(fs_data)
    return web.json_response({"ok":True})

# ── SSEARCH PROXY ─────────────────────────────────────────────────────────────
async def ssearch_proxy(request):
    """Proxy any URL through the server to bypass CORS/X-Frame-Options."""
    url = request.rel_url.query.get("url","")
    if not url:
        return web.Response(text="Missing url", status=400)
    if not url.startswith("http"):
        url = "https://" + url
    try:
        timeout = ClientTimeout(total=20)
        async with ClientSession(timeout=timeout) as s:
            # Forward with browser-like headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            async with s.get(url, headers=headers, allow_redirects=True) as resp:
                content_type = resp.headers.get("Content-Type","text/html")
                body = await resp.read()
                # If HTML, inject base tag for relative URLs
                if "text/html" in content_type:
                    html = body.decode("utf-8", errors="replace")
                    base_tag = f'<base href="{url}">'
                    if "<head>" in html.lower():
                        html = html.replace("<head>", "<head>" + base_tag, 1)
                    body = html.encode("utf-8")
                return web.Response(
                    body=body,
                    content_type=content_type.split(";")[0],
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "X-Frame-Options": "ALLOWALL",
                    }
                )
    except Exception as e:
        return web.Response(text=f"Proxy error: {e}", status=502)

# ── STATIC / APP ROUTES ───────────────────────────────────────────────────────
async def index(request):
    return web.FileResponse(os.path.join(BASE_DIR, "index.html"))

async def serve_app(request):
    name = request.match_info["name"]
    path = os.path.join(APPS_DIR, name + ".html")
    if os.path.exists(path):
        return web.FileResponse(path)
    return web.Response(status=404, text="App not found: " + name)

async def health(request):
    return web.json_response({"status":"ok","users":len(sessions)})

async def debug(request):
    """Debug endpoint to check config."""
    return web.json_response({
        "gh_token_set": bool(GH_TOKEN),
        "gh_repo": GH_REPO or "(not set)",
        "gh_branch": GH_BRANCH,
        "fs_file_exists": os.path.exists(FS_FILE),
        "fs_size": os.path.getsize(FS_FILE) if os.path.exists(FS_FILE) else 0,
        "users_in_fs": list((fs_data.get("System",{}).get("Users",{})).keys()),
        "active_sessions": len(sessions),
    })

# ── APP SETUP ─────────────────────────────────────────────────────────────────
app = web.Application(client_max_size=100*1024*1024)
app.router.add_get("/",                  index)
app.router.add_get("/health",            health)
app.router.add_get("/app/{name}",        serve_app)
# Auth
app.router.add_post("/api/auth/signup",  auth_signup)
app.router.add_post("/api/auth/login",   auth_login)
app.router.add_post("/api/auth/logout",  auth_logout)
app.router.add_post("/api/auth/check",   auth_check_user)
app.router.add_get ("/api/auth/users",   auth_list_users)
app.router.add_post("/api/auth/change-password", auth_change_password)
# Filesystem
app.router.add_get ("/api/fs/list",      fs_list)
app.router.add_get ("/api/fs/read",      fs_read)
app.router.add_post("/api/fs/write",     fs_write)
app.router.add_post("/api/fs/mkdir",     fs_mkdir)
app.router.add_post("/api/fs/delete",    fs_delete)
app.router.add_post("/api/fs/move",      fs_move)
app.router.add_post("/api/fs/upload",    fs_upload)
app.router.add_post("/api/fs/reset",     fs_reset)
# Proxy
app.router.add_get ("/api/proxy",        ssearch_proxy)

# CORS middleware
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(headers={
            "Access-Control-Allow-Origin":"*",
            "Access-Control-Allow-Methods":"GET,POST,OPTIONS",
            "Access-Control-Allow-Headers":"Content-Type,X-SD-Token"
        })
    resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,X-SD-Token"
    return resp

app.middlewares.append(cors_middleware)

# ── KEEP ALIVE ────────────────────────────────────────────────────────────────
SELF_URL = os.environ.get("SELF_URL","")
def keep_alive():
    while True:
        try:
            if SELF_URL: req_lib.get(SELF_URL+"/health", timeout=10)
        except: pass
        time.sleep(300)
threading.Thread(target=keep_alive, daemon=True).start()

port = int(os.environ.get("PORT", 8080))
print(f"SoupyDesk starting on port {port}")
web.run_app(app, host="0.0.0.0", port=port)
