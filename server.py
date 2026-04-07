"""
SoupyDesk — server.py
aiohttp backend serving the desktop and virtual filesystem
"""
import os, json, base64, mimetypes, uuid, time
from aiohttp import web

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FS_FILE  = os.path.join(BASE_DIR, "filesystem.json")
APPS_DIR = os.path.join(BASE_DIR, "apps")

# ── Bootstrap filesystem ──────────────────────────────────────────────────────
DEFAULT_FS = {
    "Desktop":   {"__type":"dir","__meta":{"icon":"folder","protected":False}},
    "Downloads": {"__type":"dir","__meta":{"icon":"folder","protected":False}},
    "Music":     {"__type":"dir","__meta":{"icon":"folder-music","protected":False}},
    "Documents": {"__type":"dir","__meta":{"icon":"folder-doc","protected":False}},
    "System": {
        "__type":"dir","__meta":{"icon":"folder-system","protected":True},
        "Main": {
            "__type":"dir","__meta":{"icon":"folder-main","protected":True},
            "SShell.app":       {"__type":"app","__meta":{"protected":True}},
            "SoupyChat.app":    {"__type":"app","__meta":{"protected":True}},
            "SSearch.app":      {"__type":"app","__meta":{"protected":True}},
            "Files.app":        {"__type":"app","__meta":{"protected":True}},
            "ControlCenter.app":{"__type":"app","__meta":{"protected":True}},
        },
        "ThirdParty": {
            "__type":"dir","__meta":{"icon":"folder-3p","protected":False}
        }
    }
}

def load_fs():
    if os.path.exists(FS_FILE):
        with open(FS_FILE, "r") as f:
            return json.load(f)
    return json.loads(json.dumps(DEFAULT_FS))

def save_fs(fs):
    with open(FS_FILE, "w") as f:
        json.dump(fs, f, indent=2)

def get_node(fs, path_parts):
    node = fs
    for p in path_parts:
        if p == "": continue
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node

def set_node(fs, path_parts, value):
    node = fs
    for p in path_parts[:-1]:
        if p == "": continue
        node = node[p]
    node[path_parts[-1]] = value

def del_node(fs, path_parts):
    node = fs
    for p in path_parts[:-1]:
        if p == "": continue
        node = node[p]
    del node[path_parts[-1]]

def parse_path(path):
    return [p for p in path.strip("/").split("/") if p]

fs = load_fs()

# ── CORS helper ───────────────────────────────────────────────────────────────
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# ── Routes ────────────────────────────────────────────────────────────────────
async def index(request):
    return web.FileResponse(os.path.join(BASE_DIR, "index.html"))

async def serve_app(request):
    name = request.match_info["name"]
    path = os.path.join(APPS_DIR, name + ".html")
    if os.path.exists(path):
        return web.FileResponse(path)
    return web.Response(status=404, text="App not found")

async def fs_list(request):
    global fs
    path  = request.rel_url.query.get("path", "/")
    parts = parse_path(path)
    node  = get_node(fs, parts) if parts else fs
    if node is None:
        return cors(web.json_response({"error":"not found"}, status=404))
    items = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("__"): continue
            if isinstance(v, dict):
                t    = v.get("__type","dir")
                meta = v.get("__meta", {})
                items.append({
                    "name": k, "type": t,
                    "icon": meta.get("icon","folder"),
                    "protected": meta.get("protected", False),
                    "size": len(v.get("__content","")) if t == "file" else None
                })
    return cors(web.json_response({"path":path, "items":items}))

async def fs_read(request):
    global fs
    path  = request.rel_url.query.get("path","")
    parts = parse_path(path)
    node  = get_node(fs, parts)
    if node is None:
        return cors(web.json_response({"error":"not found"},status=404))
    content  = node.get("__content","")
    mime     = node.get("__mime","text/plain")
    return cors(web.json_response({"content":content,"mime":mime}))

async def fs_write(request):
    global fs
    body    = await request.json()
    path    = body.get("path","")
    content = body.get("content","")
    mime    = body.get("mime","text/plain")
    meta    = body.get("meta",{})
    parts   = parse_path(path)
    if not parts:
        return cors(web.json_response({"error":"invalid path"},status=400))
    # Ensure parents exist
    node = fs
    for p in parts[:-1]:
        if p not in node:
            node[p] = {"__type":"dir","__meta":{}}
        node = node[p]
    node[parts[-1]] = {"__type":"file","__content":content,"__mime":mime,"__meta":meta}
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

async def fs_mkdir(request):
    global fs
    body  = await request.json()
    path  = body.get("path","")
    parts = parse_path(path)
    node  = fs
    for p in parts:
        if p not in node:
            node[p] = {"__type":"dir","__meta":{}}
        node = node[p]
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

async def fs_delete(request):
    global fs
    body      = await request.json()
    path      = body.get("path","")
    force     = body.get("force", False)
    parts     = parse_path(path)
    node      = get_node(fs, parts)
    if node is None:
        return cors(web.json_response({"error":"not found"},status=404))
    protected = node.get("__meta",{}).get("protected",False) if isinstance(node,dict) else False
    if protected and not force:
        return cors(web.json_response({"error":"protected","message":"This is a system file. Use force=true to delete anyway."},status=403))
    del_node(fs, parts)
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

async def fs_move(request):
    global fs
    body  = await request.json()
    src   = parse_path(body.get("src",""))
    dst   = parse_path(body.get("dst",""))
    node  = get_node(fs, src)
    if node is None:
        return cors(web.json_response({"error":"src not found"},status=404))
    set_node(fs, dst, node)
    del_node(fs, src)
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

async def fs_upload(request):
    global fs
    reader = await request.multipart()
    dest   = "/"
    while True:
        field = await reader.next()
        if field is None: break
        if field.name == "dest":
            dest = await field.text()
        elif field.name == "file":
            filename = field.filename or f"file_{uuid.uuid4().hex[:6]}"
            data     = await field.read()
            mime     = field.headers.get("Content-Type","application/octet-stream")
            # Encode to base64 for storage
            b64      = base64.b64encode(data).decode()
            parts    = parse_path(dest) + [filename]
            node     = fs
            for p in parts[:-1]:
                if p not in node:
                    node[p] = {"__type":"dir","__meta":{}}
                node = node[p]
            node[parts[-1]] = {
                "__type":"file","__content":b64,
                "__mime":mime,"__meta":{"uploaded":True}
            }
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

async def fs_reset(request):
    """Reset filesystem to defaults"""
    global fs
    fs = json.loads(json.dumps(DEFAULT_FS))
    save_fs(fs)
    return cors(web.json_response({"ok":True}))

# ── App setup ─────────────────────────────────────────────────────────────────
app = web.Application(client_max_size=50*1024*1024)  # 50MB upload limit
app.router.add_get("/",                   index)
app.router.add_get("/app/{name}",         serve_app)
app.router.add_get("/api/fs/list",        fs_list)
app.router.add_get("/api/fs/read",        fs_read)
app.router.add_post("/api/fs/write",      fs_write)
app.router.add_post("/api/fs/mkdir",      fs_mkdir)
app.router.add_post("/api/fs/delete",     fs_delete)
app.router.add_post("/api/fs/move",       fs_move)
app.router.add_post("/api/fs/upload",     fs_upload)
app.router.add_post("/api/fs/reset",      fs_reset)

# ── Keep alive ────────────────────────────────────────────────────────────────
import threading, requests as req_lib
SELF_URL = os.environ.get("SELF_URL","")
def keep_alive():
    while True:
        try:
            if SELF_URL: req_lib.get(SELF_URL, timeout=10)
        except: pass
        time.sleep(360)
threading.Thread(target=keep_alive, daemon=True).start()

port = int(os.environ.get("PORT", 8080))
web.run_app(app, host="0.0.0.0", port=port)
