#!/usr/bin/env python3
"""Cartographie l'API d'un site à partir d'un export HAR de Chrome DevTools.

Usage :
    python tools/har_explore.py capture.har [--host wiki-masters] [--depth 3] > api.md

Regroupe les requêtes par (méthode, chemin normalisé), affiche les paramètres, les
codes de retour et la FORME des réponses JSON (clés + types, sans les valeurs),
ainsi que les messages WebSocket. Les cookies et tokens ne sont jamais affichés.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

ID_RE = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{36}|[A-Za-z0-9_-]{20,})$")
SENSITIVE = {"cookie", "authorization", "x-csrf-token", "x-xsrf-token", "set-cookie"}


def norm_path(path: str) -> str:
    return "/".join("{id}" if ID_RE.match(p) else p for p in path.split("/"))


def shape(v, depth: int):
    if depth < 0:
        return "…"
    if isinstance(v, dict):
        return {k: shape(x, depth - 1) for k, x in list(v.items())[:40]}
    if isinstance(v, list):
        return [shape(v[0], depth - 1), f"×{len(v)}"] if v else []
    return type(v).__name__


def parse_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("har")
    ap.add_argument("--host", default="", help="ne garder que les hôtes contenant ce texte")
    ap.add_argument("--depth", type=int, default=3)
    a = ap.parse_args()

    entries = json.load(open(a.har, encoding="utf-8"))["log"]["entries"]
    groups: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "status": set(), "query": set(),
                                                     "auth": set(), "req": None, "resp": None})
    ws_msgs: dict[str, list] = defaultdict(list)

    for e in entries:
        req, resp = e["request"], e["response"]
        u = urlparse(req["url"])
        if a.host not in u.netloc:
            continue
        mime = resp.get("content", {}).get("mimeType", "")
        if e.get("_resourceType") == "websocket" or req["url"].startswith("ws"):
            for m in e.get("_webSocketMessages", []):
                ws_msgs[f"{u.netloc}{u.path}"].append((m.get("type"), m.get("data")))
            continue
        if "json" not in mime and req["method"] == "GET":
            continue  # ignore html/js/css/images
        g = groups[(req["method"], u.netloc, norm_path(u.path))]
        g["n"] += 1
        g["status"].add(resp["status"])
        g["query"] |= set(parse_qs(u.query))
        g["auth"] |= {h["name"].lower() for h in req["headers"] if h["name"].lower() in SENSITIVE}
        body = parse_json(req.get("postData", {}).get("text"))
        if body is not None and g["req"] is None:
            g["req"] = shape(body, a.depth)
        rj = parse_json(resp.get("content", {}).get("text"))
        if rj is not None and g["resp"] is None:
            g["resp"] = shape(rj, a.depth)

    print(f"# Endpoints ({len(groups)})\n")
    for (method, host, path), g in sorted(groups.items(), key=lambda kv: (kv[0][2], kv[0][0])):
        print(f"## {method} {path}  \n`{host}` · ×{g['n']} · status {sorted(g['status'])}")
        if g["query"]:
            print(f"- query : {', '.join(sorted(g['query']))}")
        if g["auth"]:
            print(f"- auth : {', '.join(sorted(g['auth']))} (valeurs masquées)")
        if g["req"] is not None:
            print("- corps envoyé :\n```json\n" + json.dumps(g["req"], ensure_ascii=False, indent=1) + "\n```")
        if g["resp"] is not None:
            print("- réponse :\n```json\n" + json.dumps(g["resp"], ensure_ascii=False, indent=1)[:3000] + "\n```")
        print()

    if ws_msgs:
        print("# WebSockets\n")
        for url, msgs in ws_msgs.items():
            print(f"## {url} ({len(msgs)} messages)")
            seen = set()
            for typ, data in msgs:
                j = parse_json(data)
                key = json.dumps(shape(j, 2), sort_keys=True) if j is not None else (data or "")[:60]
                if key in seen:
                    continue
                seen.add(key)
                print(f"- {typ}: `{key[:400]}`")
                if len(seen) > 15:
                    break
            print()


if __name__ == "__main__":
    sys.exit(main())
