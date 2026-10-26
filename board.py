#!/usr/bin/env python3
"""Local FreeHire board. Run serve, publish INPUT.json, or export-active."""
import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
STATUSES = {"active", "applied", "dismissed"}


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical_url(value):
    p = urlsplit(value or "")
    if p.scheme not in ("https", "http") or not p.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source"}]
    # Some ATSs (e.g. Mokahr) put the actual job ID in #/job/<id>.
    # Keep fragments so different openings never share a suppression key.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(sorted(query)), p.fragment))


def identities(job):
    keys = []
    if job.get("public_slug"):
        keys.append("slug:" + job["public_slug"])
    if job.get("source") and job.get("external_id"):
        keys.append("source:" + job["source"] + ":" + str(job["external_id"]))
    url = canonical_url(job.get("url") or job.get("application_url"))
    if url:
        keys.append("url:" + url)
    keys.extend(k for k in job.get("identity_aliases", []) if isinstance(k, str) and k.startswith(("slug:", "source:", "url:")))
    return list(dict.fromkeys(keys))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Board:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS decisions (identity TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(str(self.root / "decisions.sqlite3"), timeout=20)

    def catalog(self):
        path = self.root / "jobs.json"
        return json.loads(path.read_text()) if path.exists() else {"jobs": [], "updated_at": None}

    def snapshot(self):
        catalog = self.catalog()
        with self.connect() as db:
            saved = {r[0]: (r[1], r[2]) for r in db.execute("SELECT identity,status,updated_at FROM decisions")}
        jobs = []
        for original in catalog.get("jobs", []):
            job = dict(original)
            keys = identities(job)
            if not keys:
                continue
            decisions = [saved[k] for k in keys if k in saved]
            status, stamp = max(decisions, key=lambda x: x[1]) if decisions else ("active", None)
            job.update(key=keys[0], status=status, status_updated_at=stamp)
            jobs.append(job)
        return {**catalog, "jobs": jobs}

    def decide(self, key, status):
        if status not in STATUSES:
            raise ValueError("未知状态")
        job = next((j for j in self.snapshot()["jobs"] if j["key"] == key), None)
        if not job:
            raise ValueError("岗位不存在，请刷新后重试")
        stamp = now()
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO decisions VALUES (?,?,?)", [(k, status, stamp) for k in identities(job)])
        return self.snapshot()

    def publish(self, data):
        if isinstance(data, list):
            data = {"jobs": data}
        incoming = data.get("jobs")
        if not isinstance(incoming, list) or any(not isinstance(j, dict) or not identities(j) for j in incoming):
            raise ValueError("输入需包含jobs数组，每项应有public_slug或职位ID/申请链接")
        # Keep marked records available for undo even after they age out of new searches.
        history = [j for j in self.snapshot()["jobs"] if j["status"] != "active"]
        combined, seen = [], set()
        for j in incoming + history:
            keys = identities(j)
            if any(k in seen for k in keys):
                continue
            seen.update(keys)
            combined.append({k: v for k, v in j.items() if k not in {"key", "status", "status_updated_at"}})
        result = {**data, "updated_at": now(), "jobs": combined}
        atomic_json(self.root / "jobs.json", result)
        return self.snapshot()


def handler_for(board):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, kind="application/json; charset=utf-8"):
            payload = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def allowed_host(self):
            return self.headers.get("Host") in {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Invalid host"})
            if self.path == "/api/jobs":
                return self.send(200, board.snapshot())
            if self.path == "/api/audit":
                return self.send(200, json.loads((board.root / "audit-index.json").read_text()))
            if self.path == "/audit.html":
                return self.send(200, (ROOT / "audit.html").read_bytes(), "text/html; charset=utf-8")
            if self.path in ("/", "/index.html"):
                return self.send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Invalid host"})
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.send(403, {"error": "Invalid origin"})
            if self.path != "/api/decision":
                return self.send(404, {"error": "Not found"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "JSON required"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("请求大小无效")
                data = json.loads(self.rfile.read(size))
                result = board.decide(data["key"], data["status"])
                self.send(200, result)
            except (ValueError, KeyError, TypeError) as error:
                self.send(400, {"error": str(error)})
            except Exception:
                self.send(500, {"error": "保存失败，请重试；标记尚未确认保存"})

        def log_message(self, fmt, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "publish", "export-active", "export-all"])
    parser.add_argument("input", nargs="?")
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    board = Board()
    if args.command == "serve":
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(board))
        print("FreeHire board: http://127.0.0.1:%s" % args.port, flush=True)
        server.serve_forever()
    elif args.command == "publish":
        if not args.input:
            parser.error("publish需要输入JSON文件")
        print(json.dumps({"count": len(board.publish(json.loads(Path(args.input).read_text()))["jobs"])}, ensure_ascii=False))
    else:
        result = board.snapshot()
        if args.command == "export-active":
            result["jobs"] = [j for j in result["jobs"] if j["status"] == "active"]
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
