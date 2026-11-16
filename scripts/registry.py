#!/usr/bin/env python3
"""Check the registry's files, and build the index conch reads.

    registry.py check [--base REF]   every file, and host changes since REF
    registry.py build OUT            OUT/index.json (every kind, format 2),
                                     OUT/providers/NAME.toml, OUT/integrations/NAME.toml,
                                     OUT/legacy/ (the sandbox providers in format 1,
                                     for conches from before the move), and
                                     OUT/index.json.sig when CONCH_REGISTRY_SIGNING_KEY is set

A folder per kind: sandbox/NAME/{provider.toml, meta.json} for sandbox
providers, and ci|tickets|notify/NAME/{integration.toml, meta.json} for
integration files (conch's format 3). conch checks each file itself;
this checks what conch does not: the folder's shape, meta.json, that no
secret was committed, and that a file's hosts did not move — a file sends
the person's key to its api host, so a new host is a new destination for
everybody's key, and needs a maintainer's label.
"""

import base64
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ROOT / "sandbox"
# The integration kinds this registry holds, each a folder of its own.
KINDS = ("ci", "tickets", "notify")
INTEGRATION_FILES = {"integration.toml", "meta.json", "README.md"}
INTEGRATION_META_KEYS = {"version", "adapted_by", "adapted", "docs", "conch", "checked", "revoked"}
INTEGRATION_CHECKED_KEYS = {"date", "conch", "detail"}
# What an integration file's operations are, by kind: what conch's
# contract for that kind calls them.
OPERATIONS = {"ci": ("runs", "failed_log", "rerun", "stats"),
              "tickets": ("list", "get", "comment", "link", "move"),
              "notify": ("send",)}
NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
FILES = {"provider.toml", "meta.json", "README.md"}
FORMATS = {1, 2}
MAX_BYTES = 256 << 10
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
META_KEYS = {"adapted_by", "adapted", "docs", "conch", "checked"}
CHECKED_KEYS = {"date", "conch", "sandboxes"}

# What a committed credential looks like. A provider file holds none —
# keys are read from the variable key_env names, and conch's public key is
# {public_key} — so anything here is a mistake.
SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bssh-(ed25519|rsa|dss) AAAA"), "an ssh key"),
    (re.compile(r"\becdsa-sha2-nistp\d+ AAAA"), "an ssh key"),
    (re.compile(r"\b(dop_v1_|ghp_|gho_|github_pat_|sk-|xox[bap]-|AKIA)[A-Za-z0-9_\-]{8,}"), "an API token"),
    (re.compile(r"(?i)\b(token|secret|password|api_?key)\s*=\s*\"[^\"{}]{8,}\""), "a credential"),
    (re.compile(r"[A-Za-z0-9+/_\-]{40,}"), "a long token"),
]


def hosts(f):
    api = urlparse(f.get("api", "")).hostname or ""
    return api, (f.get("ssh") or {}).get("host", "")


def load(folder):
    """The folder's provider file and meta, and what is wrong with them."""
    problems = []
    name = folder.name
    say = lambda msg: problems.append(f"{name}: {msg}")
    if not NAME.match(name):
        say("the folder's name: lowercase letters, digits and -, starting with a letter")
    present = {p.name for p in folder.iterdir()}
    for extra in sorted(present - FILES):
        say(f"{extra}: only provider.toml, meta.json and README.md belong here")
    for need in ("provider.toml", "meta.json"):
        if need not in present:
            say(f"no {need}")
    if problems and not {"provider.toml", "meta.json"} <= present:
        return None, None, problems

    raw = (folder / "provider.toml").read_bytes()
    meta_raw = (folder / "meta.json").read_bytes()
    if len(raw) > MAX_BYTES or len(meta_raw) > MAX_BYTES:
        say("over 256 KB")
        return None, None, problems
    for text, what in ((raw.decode("utf-8", "replace"), "provider.toml"), (meta_raw.decode("utf-8", "replace"), "meta.json")):
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for pattern, kind in SECRETS:
                # A URL is long and is not a secret.
                scrubbed = re.sub(r"https?://\S+", "", line)
                if pattern.search(scrubbed):
                    say(f"{what}:{line_no} looks like {kind}; a provider file never holds one")
                    break
    try:
        f = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        say(f"provider.toml: {e}")
        return None, None, problems
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError as e:
        say(f"meta.json: {e}")
        return f, None, problems

    if f.get("name") != name:
        say(f"provider.toml names {f.get('name')!r}; the folder is {name!r}")
    if f.get("format", 1) not in FORMATS:
        say(f"format {f.get('format')!r}: one of {sorted(FORMATS)}")
    api = urlparse(f.get("api", ""))
    if api.scheme != "https" or not api.hostname:
        say("api: an https:// URL")
    elif api.hostname in ("localhost", "127.0.0.1", "::1"):
        say("api: a provider on the internet, not this computer")

    if not isinstance(meta, dict):
        say("meta.json: an object")
        return f, None, problems
    for k in sorted(set(meta) - META_KEYS):
        say(f"meta.json: unknown key {k}")
    for k in sorted(META_KEYS - set(meta)):
        say(f"meta.json: no {k}")
    if not isinstance(meta.get("adapted_by"), str) or not meta.get("adapted_by"):
        say("meta.json adapted_by: who wrote it — an agent's name, or a person's")
    if not DATE.match(str(meta.get("adapted", ""))):
        say("meta.json adapted: YYYY-MM-DD")
    if urlparse(str(meta.get("docs", ""))).scheme != "https":
        say("meta.json docs: the https:// URL it was adapted from")
    if not VERSION.match(str(meta.get("conch", ""))):
        say("meta.json conch: the conch version it was written for, e.g. 0.1.10")
    checked = meta.get("checked")
    if checked is not None:
        if not isinstance(checked, dict):
            say("meta.json checked: null, or {date, conch, sandboxes}")
        else:
            for k in sorted(set(checked) - CHECKED_KEYS):
                say(f"meta.json checked: unknown key {k}")
            if not DATE.match(str(checked.get("date", ""))):
                say("meta.json checked.date: YYYY-MM-DD")
            if not VERSION.match(str(checked.get("conch", ""))):
                say("meta.json checked.conch: a version, e.g. 0.1.10")
            if not isinstance(checked.get("sandboxes"), int) or checked.get("sandboxes") < 0:
                say("meta.json checked.sandboxes: how many the key listed")
    return f, meta, problems


def at_base(ref, name):
    try:
        out = subprocess.run(["git", "show", f"{ref}:sandbox/{name}/provider.toml"], cwd=ROOT,
                             capture_output=True, check=True)
    except subprocess.CalledProcessError:
        return None
    try:
        return tomllib.loads(out.stdout.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def folders():
    if not PROVIDERS.is_dir():
        return []
    return sorted(p for p in PROVIDERS.iterdir() if not p.name.startswith("."))


def check(base=None):
    problems = []
    for folder in folders():
        if not folder.is_dir():
            problems.append(f"{folder.name}: sandbox/ holds a folder per provider")
            continue
        f, _, p = load(folder)
        problems += p
        if base and f is not None:
            old = at_base(base, folder.name)
            if old is not None and hosts(old) != hosts(f) and os.environ.get("ALLOW_HOST_CHANGE") != "true":
                problems.append(f"{folder.name}: moves from {hosts(old)} to {hosts(f)}; a maintainer has to label the pull request host-change")
    for kind, folder in integration_folders():
        if not folder.is_dir():
            problems.append(f"{folder.name}: {kind}/ holds a folder per integration")
            continue
        f, _, p = load_integration(kind, folder)
        problems += p
        if base and f is not None:
            old = integration_at_base(base, kind, folder.name)
            if old is not None and integration_hosts(old) != integration_hosts(f) and os.environ.get("ALLOW_HOST_CHANGE") != "true":
                problems.append(f"{kind}/{folder.name}: moves from {integration_hosts(old)} to {integration_hosts(f)}; a maintainer has to label the pull request host-change")
    return problems


def integration_folders():
    out = []
    for kind in KINDS:
        d = ROOT / kind
        if d.is_dir():
            out += [(kind, p) for p in sorted(d.iterdir()) if not p.name.startswith(".")]
    return out


def integration_hosts(f):
    api = urlparse(f.get("api", "")).hostname or ("ask" if f.get("base_url") == "ask" else "")
    return api, tuple(sorted(f.get("follow_hosts", [])))


def integration_at_base(ref, kind, name):
    try:
        out = subprocess.run(["git", "show", f"{ref}:{kind}/{name}/integration.toml"], cwd=ROOT,
                             capture_output=True, check=True)
        return tomllib.loads(out.stdout.decode("utf-8"))
    except (subprocess.CalledProcessError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def scan_secrets(text, what, say):
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        scrubbed = re.sub(r"https?://\S+", "", line)
        for pattern, kind in SECRETS:
            if pattern.search(scrubbed):
                say(f"{what}:{line_no} looks like {kind}; a file here never holds one")
                break


def load_integration(kind, folder):
    """An integration folder's file and meta, and what is wrong with them."""
    problems = []
    name = folder.name
    say = lambda msg: problems.append(f"{kind}/{name}: {msg}")
    if not NAME.match(name):
        say("the folder's name: lowercase letters, digits and -, starting with a letter")
    present = {p.name for p in folder.iterdir()}
    for extra in sorted(present - INTEGRATION_FILES):
        say(f"{extra}: only integration.toml, meta.json and README.md belong here")
    for need in ("integration.toml", "meta.json"):
        if need not in present:
            say(f"no {need}")
    if not {"integration.toml", "meta.json"} <= present:
        return None, None, problems
    raw = (folder / "integration.toml").read_bytes()
    meta_raw = (folder / "meta.json").read_bytes()
    if len(raw) > MAX_BYTES or len(meta_raw) > MAX_BYTES:
        say("over 256 KB")
        return None, None, problems
    scan_secrets(raw.decode("utf-8", "replace"), "integration.toml", say)
    scan_secrets(meta_raw.decode("utf-8", "replace"), "meta.json", say)
    try:
        f = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        say(f"integration.toml: {e}")
        return None, None, problems
    if f.get("name") != name:
        say(f"integration.toml names {f.get('name')!r}; the folder is {name!r}")
    if f.get("kind") != kind:
        say(f"integration.toml is kind {f.get('kind')!r}; it is in {kind}/")
    if f.get("format") != 3:
        say("format = 3: an integration file says so")
    if f.get("base_url") != "ask" or f.get("api"):
        api = urlparse(f.get("api", ""))
        if api.scheme != "https" or not api.hostname:
            say("api: an https:// URL")
        elif api.hostname in ("localhost", "127.0.0.1", "::1"):
            say("api: a service on the internet, not this computer")
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError as e:
        say(f"meta.json: {e}")
        return f, None, problems
    if not isinstance(meta, dict):
        say("meta.json: an object")
        return f, None, problems
    for k in sorted(set(meta) - INTEGRATION_META_KEYS):
        say(f"meta.json: unknown key {k}")
    for k in sorted({"version", "adapted_by", "adapted", "docs", "conch", "checked"} - set(meta)):
        say(f"meta.json: no {k}")
    if not isinstance(meta.get("version"), int) or meta.get("version", 0) < 1:
        say("meta.json version: 1, and one more with every change (a version is never reused)")
    if not isinstance(meta.get("adapted_by"), str) or not meta.get("adapted_by"):
        say("meta.json adapted_by: who wrote it")
    if not DATE.match(str(meta.get("adapted", ""))):
        say("meta.json adapted: YYYY-MM-DD")
    if urlparse(str(meta.get("docs", ""))).scheme != "https":
        say("meta.json docs: the https:// URL it was adapted from")
    if not VERSION.match(str(meta.get("conch", ""))):
        say("meta.json conch: the conch version it was written for, e.g. 0.2.1")
    checked = meta.get("checked")
    if checked is not None:
        if not isinstance(checked, dict):
            say("meta.json checked: null, or {date, conch, detail}")
        else:
            for k in sorted(set(checked) - INTEGRATION_CHECKED_KEYS):
                say(f"meta.json checked: unknown key {k}")
            if not DATE.match(str(checked.get("date", ""))):
                say("meta.json checked.date: YYYY-MM-DD")
            if not VERSION.match(str(checked.get("conch", ""))):
                say("meta.json checked.conch: a version, e.g. 0.2.1")
    for r in meta.get("revoked") or []:
        if not isinstance(r, dict) or not isinstance(r.get("version"), int) or not r.get("reason"):
            say("meta.json revoked: a list of {version, reason}")
    return f, meta, problems


def build(out):
    out = Path(out)
    (out / "providers").mkdir(parents=True, exist_ok=True)
    (out / "integrations").mkdir(parents=True, exist_ok=True)
    (out / "legacy" / "providers").mkdir(parents=True, exist_ok=True)
    legacy, entries = [], []
    for folder in folders():
        f, meta, problems = load(folder)
        if problems:
            raise SystemExit("\n".join(problems))
        raw = (folder / "provider.toml").read_bytes()
        (out / "providers" / f"{folder.name}.toml").write_bytes(raw)
        (out / "legacy" / "providers" / f"{folder.name}.toml").write_bytes(raw)
        api, ssh_host = hosts(f)
        old = {
            "name": folder.name,
            "label": f.get("label") or folder.name,
            "api": f["api"],
            "api_host": api,
            "ssh_host": ssh_host,
            "key_env": f.get("key_env", ""),
            "format": f.get("format", 1),
            "note": f.get("note", ""),
            "file": f"providers/{folder.name}.toml",
            "sha256": hashlib.sha256(raw).hexdigest(),
            **{k: meta[k] for k in ("adapted_by", "adapted", "docs", "conch", "checked")},
        }
        legacy.append(old)
        # Format 2 keeps format 1's fields for a sandbox provider, which
        # conch's sandbox installer reads, beside the ones every kind has.
        entries.append({**old, "kind": "sandbox", "version": 1, "hosts": {"api": api, "ssh": ssh_host},
                        "tier": "verified" if meta.get("checked") else "community"})
    for kind, folder in integration_folders():
        f, meta, problems = load_integration(kind, folder)
        if problems:
            raise SystemExit("\n".join(problems))
        raw = (folder / "integration.toml").read_bytes()
        (out / "integrations" / f"{folder.name}.toml").write_bytes(raw)
        api, follow = integration_hosts(f)
        e = {
            "kind": kind,
            "name": folder.name,
            "label": f.get("label") or folder.name,
            "version": meta["version"],
            "format": f.get("format", 3),
            "file": f"integrations/{folder.name}.toml",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "hosts": {"api": "" if api == "ask" else api, "follow": list(follow)},
            "key_env": f.get("key_env", ""),
            "operations": [op for op in OPERATIONS.get(kind, ()) if op in f],
            "tier": "verified" if meta.get("checked") else "community",
            "checked": meta.get("checked"),
            "note": f.get("note", ""),
            "docs": meta["docs"],
            "adapted_by": meta["adapted_by"],
            "adapted": meta["adapted"],
        }
        user_env = (f.get("auth") or {}).get("user_env")
        if user_env:
            e["user_env"] = user_env
        if meta.get("revoked"):
            e["revoked"] = meta["revoked"]
        entries.append(e)
    entries.sort(key=lambda e: (e["kind"], e["name"]))
    data = (json.dumps({"format": 2, "entries": entries}, indent=2) + "\n").encode()
    (out / "index.json").write_bytes(data)
    (out / "legacy" / "index.json").write_text(json.dumps({"format": 1, "providers": legacy}, indent=2) + "\n")
    key = os.environ.get("CONCH_REGISTRY_SIGNING_KEY", "").strip()
    if key:
        (out / "index.json.sig").write_text(sign(key, data) + "\n")
    rows = "\n".join(
        f"<tr><td>{html.escape(e['label'])}</td><td>{html.escape(e['kind'])}</td><td><code>{html.escape(e['name'])}</code></td>"
        f"<td>{html.escape(e['hosts']['api'] or 'your own server')}</td><td>{'checked ' + e['checked']['date'] if e.get('checked') else 'not checked live yet'}</td></tr>"
        for e in entries)
    (out / "index.html").write_text(f"""<!DOCTYPE html>
<meta charset="utf-8"><title>conch integrations</title>
<style>body{{font:15px system-ui;margin:3em auto;max-width:52em;padding:0 1em}}td,th{{padding:.3em 1em .3em 0;text-align:left}}</style>
<h1>conch integrations</h1>
<p>Install one with <code>conch integration install NAME</code> (a sandbox provider: <code>conch sandbox provider install NAME</code>). The list as conch reads it is <a href="index.json">index.json</a>; how to add one is in the <a href="https://github.com/Amitgb14/conch-integrations">repository</a>.</p>
<table><tr><th>Integration</th><th>Kind</th><th>Name</th><th>API</th><th>Live check</th></tr>
{rows}
</table>
""")
    return entries


# An ed25519 private key in PKCS #8, around its 32-byte seed: what openssl
# reads, so signing needs nothing beyond the runner's own tools.
_ED25519_PREFIX = bytes.fromhex("302e020100300506032b657004220420")


def sign(private_b64, data):
    """The index's signature, base64: ed25519 over its exact bytes, as
    conch's integration.Verify checks it."""
    try:
        seed = base64.b64decode(private_b64, validate=True)
    except ValueError:
        seed = b""
    if len(seed) != 32:
        raise SystemExit("CONCH_REGISTRY_SIGNING_KEY is not a base64 ed25519 seed")
    with tempfile.TemporaryDirectory() as d:
        key, msg, sig = Path(d) / "key.der", Path(d) / "msg", Path(d) / "sig"
        key.write_bytes(_ED25519_PREFIX + seed)
        os.chmod(key, 0o600)
        msg.write_bytes(data)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-keyform", "DER", "-rawin",
                        "-in", str(msg), "-out", str(sig)], check=True)
        return base64.b64encode(sig.read_bytes()).decode()


def main(argv):
    if len(argv) >= 1 and argv[0] == "check":
        base = argv[2] if len(argv) == 3 and argv[1] == "--base" else None
        if len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--base"):
            raise SystemExit(__doc__)
        problems = check(base)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            return 1
        print(f"{len(folders())} sandbox providers and {len(integration_folders())} integrations, no problems")
        return 0
    if len(argv) == 2 and argv[0] == "build":
        print(f"{len(build(argv[1]))} entries indexed")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
