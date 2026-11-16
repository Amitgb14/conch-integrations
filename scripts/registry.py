#!/usr/bin/env python3
"""Check the provider files, and build the index conch reads.

    registry.py check [--base REF]   every provider, and host changes since REF
    registry.py build OUT            OUT/index.json and OUT/providers/NAME.toml
    registry.py conch-check [CONCH]  conch's own check of every file

A provider with no plain-ssh way in is still described, its API in full
and its [ssh] left out, with "enabled": false in meta.json. conch cloud
will reach such sandboxes through a public URL; until a conch can, the
index lists them under "disabled", apart from the providers it offers.

conch checks each file itself (conch sandbox provider check -offline);
this checks what conch does not: the folder's shape, meta.json, that no
secret was committed, and that a provider's hosts did not move — a file
sends the person's API key to its api host, so a new host is a new
destination for everybody's key, and needs a maintainer's label.
"""

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ROOT / "providers"
NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
BUILTIN = {"daytona", "boat", "devin", "tensorlake"}
FILES = {"provider.toml", "meta.json", "README.md"}
FORMATS = {1, 2}
MAX_BYTES = 256 << 10
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
META_KEYS = {"adapted_by", "adapted", "docs", "conch", "checked"}
OPTIONAL_META = {"enabled"}
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
    if name in BUILTIN:
        say("conch has this provider built in")
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
    for k in sorted(set(meta) - META_KEYS - OPTIONAL_META):
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
    enabled = meta.get("enabled", True)
    if not isinstance(enabled, bool):
        say("meta.json enabled: true or false")
    elif enabled and "ssh" not in f:
        say('no [ssh]: conch reaches a sandbox over ssh; with none yet, set "enabled": false in meta.json')
    elif not enabled and "ssh" in f:
        say('has [ssh] but meta.json says "enabled": false; drop one')
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
        out = subprocess.run(["git", "show", f"{ref}:providers/{name}/provider.toml"], cwd=ROOT,
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
            problems.append(f"{folder.name}: providers/ holds a folder per provider")
            continue
        f, _, p = load(folder)
        problems += p
        if base and f is not None:
            old = at_base(base, folder.name)
            if old is not None and hosts(old) != hosts(f) and os.environ.get("ALLOW_HOST_CHANGE") != "true":
                problems.append(f"{folder.name}: moves from {hosts(old)} to {hosts(f)}; a maintainer has to label the pull request host-change")
    return problems


def enabled(meta):
    return meta.get("enabled", True) is True


def conch_check(conch="conch"):
    """conch sandbox provider check -offline on every file. A provider that
    is off has no [ssh] by design, so conch's [ssh] problems are expected
    of it; anything else is a problem either way."""
    problems = []
    for folder in folders():
        _, meta, _ = load(folder)
        off = meta is not None and not enabled(meta)
        out = subprocess.run([conch, "sandbox", "provider", "check", "-offline", str(folder / "provider.toml")],
                             capture_output=True, text=True)
        said = [l.strip()[2:] for l in (out.stdout + out.stderr).splitlines() if l.strip().startswith("- ")]
        left = [p for p in said if not (off and p.startswith("[ssh]"))]
        if out.returncode != 0 and (not off or left or not said):
            problems += [f"{folder.name}: {p}" for p in left] or [f"{folder.name}: conch check failed: {(out.stdout + out.stderr).strip()}"]
    return problems


def build(out):
    out = Path(out)
    (out / "providers").mkdir(parents=True, exist_ok=True)
    entries = []
    for folder in folders():
        f, meta, problems = load(folder)
        if problems:
            raise SystemExit("\n".join(problems))
        raw = (folder / "provider.toml").read_bytes()
        (out / "providers" / f"{folder.name}.toml").write_bytes(raw)
        api, ssh_host = hosts(f)
        entries.append({
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
            "enabled": enabled(meta),
            **{k: meta[k] for k in ("adapted_by", "adapted", "docs", "conch", "checked")},
        })
    index = {"format": 1, "providers": [e for e in entries if e["enabled"]],
             "disabled": [e for e in entries if not e["enabled"]]}
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    rows = "\n".join(
        f"<tr><td>{html.escape(e['label'])}</td><td><code>{html.escape(e['name'])}</code></td>"
        f"<td>{html.escape(e['api_host'])}</td><td>{'off: no ssh yet' if not e['enabled'] else 'checked ' + e['checked']['date'] if e['checked'] else 'not checked live yet'}</td></tr>"
        for e in entries)
    (out / "index.html").write_text(f"""<!DOCTYPE html>
<meta charset="utf-8"><title>conch sandbox providers</title>
<style>body{{font:15px system-ui;margin:3em auto;max-width:46em;padding:0 1em}}td,th{{padding:.3em 1em .3em 0;text-align:left}}</style>
<h1>conch sandbox providers</h1>
<p>Install one with <code>conch sandbox provider install NAME</code>. The list as conch reads it is <a href="index.json">index.json</a>; how to add one is in the <a href="https://github.com/Amitgb14/conch-sandbox-providers">repository</a>.</p>
<table><tr><th>Provider</th><th>Name</th><th>API</th><th>Live check</th></tr>
{rows}
</table>
""")
    return entries


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
        print(f"{len(folders())} providers, no problems")
        return 0
    if len(argv) in (1, 2) and argv[0] == "conch-check":
        problems = conch_check(*argv[1:])
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    if len(argv) == 2 and argv[0] == "build":
        print(f"{len(build(argv[1]))} providers indexed")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
