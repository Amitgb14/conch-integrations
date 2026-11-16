#!/usr/bin/env python3
"""Check the registry's files, and build the index conch reads.

    registry.py check [--base REF]   every file, and host changes since REF
    registry.py build OUT            OUT/index.json (every kind, format 2),
                                     OUT/providers/NAME.toml, OUT/integrations/NAME.toml,
                                     OUT/legacy/ (the sandbox providers in format 1,
                                     for conches from before the move), and
                                     OUT/index.json.sig when CONCH_REGISTRY_SIGNING_KEY is set
    registry.py conch-check [CONCH]  conch's own check of every sandbox provider

A folder per kind: sandbox/NAME/{provider.toml, meta.json} for sandbox
providers, and ci|tickets|notify/NAME/{integration.toml, meta.json} for
integration files (conch's format 3). conch checks each file itself;
this checks what conch does not: the folder's shape, meta.json, that no
secret was committed, and that a file's hosts did not move — a file sends
the person's key to its api host, so a new host is a new destination for
everybody's key, and needs a maintainer's label.

A sandbox provider with no plain-ssh way in is still described, its API
in full and its [ssh] left out, with "enabled": false in meta.json. conch
cloud will reach such sandboxes through a public URL; until a conch can,
both indexes list them under "disabled", apart from the providers conch
offers.
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
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ROOT / "sandbox"
# The integration kinds this registry holds, each a folder of its own.
KINDS = ("ci", "tickets", "notify")
# What conch has built in: listed with the rest so the catalog is one
# place, but with no file — conch's own code is what runs them.
BUILTIN = ROOT / "builtin.json"
BUILTIN_KINDS = {"host", "ci", "tickets", "notify", "sandbox"}
BUILTIN_KEYS = {"kind", "name", "label", "docs", "note", "key_env"}
INTEGRATION_FILES = {"integration.toml", "meta.json", "README.md"}
INTEGRATION_META_KEYS = {"version", "adapted_by", "adapted", "docs", "conch", "checked", "revoked"}
INTEGRATION_CHECKED_KEYS = {"date", "conch", "detail"}
# What an integration file's operations are, by kind: what conch's
# contract for that kind calls them.
OPERATIONS = {"ci": ("runs", "failed_log", "rerun", "stats"),
              "tickets": ("list", "get", "comment", "link", "move"),
              "notify": ("send",)}
NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
ICONS = ("icon.svg", "icon.png")
FILES = {"provider.toml", "meta.json", "README.md", *ICONS}
MAX_ICON = 32 << 10
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FORMATS = {1, 2, 3, 4}
# What a released conch from before the integrations reads, through the
# old address (legacy/): format 4 is conch's own providers as files, which
# those conches have built in and would refuse.
LEGACY_FORMATS = {1, 2, 3}
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


def icon(folder):
    """The provider's icon file, or None."""
    return next((folder / i for i in ICONS if (folder / i).is_file()), None)


def check_icon(folder, present, say):
    """An icon is drawn by conch and on the site, so it must be a plain
    picture: nothing that runs, and nothing fetched from elsewhere."""
    have = [i for i in ICONS if i in present]
    if len(have) > 1:
        say("one icon: icon.svg or icon.png, not both")
    for name in have:
        raw = (folder / name).read_bytes()
        if len(raw) > MAX_ICON:
            say(f"{name}: over 32 KB")
            continue
        if name == "icon.png":
            if not raw.startswith(PNG_MAGIC) or raw[12:16] != b"IHDR":
                say("icon.png: not a PNG")
                continue
            width, height = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
            if width != height:
                say(f"icon.png: {width}x{height}; an icon is square")
            elif width < 64:
                say(f"icon.png: {width}px; at least 64px across")
            continue
        text = raw.decode("utf-8", "replace")
        if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
            say("icon.svg: no DOCTYPE or ENTITY")
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            say(f"icon.svg: {e}")
            continue
        local = lambda tag: tag.rsplit("}", 1)[-1]
        if local(root.tag) != "svg":
            say("icon.svg: an <svg> at the top")
        for el in root.iter():
            tag = local(el.tag) if isinstance(el.tag, str) else ""
            if tag in ("script", "foreignObject", "iframe", "embed", "object", "a"):
                say(f"icon.svg: no <{tag}>")
            for attr, value in el.attrib.items():
                attr = local(attr)
                if attr.lower().startswith("on"):
                    say(f"icon.svg: no {attr} handler")
                elif attr == "href" and not value.startswith("#"):
                    say(f"icon.svg: href {value!r} reaches outside the file")
        if "@import" in text or re.search(r"url\(\s*['\"]?(?!#)", text):
            say("icon.svg: a url() or @import reaches outside the file")


def load(folder):
    """The folder's provider file and meta, and what is wrong with them."""
    problems = []
    name = folder.name
    say = lambda msg: problems.append(f"{name}: {msg}")
    if not NAME.match(name):
        say("the folder's name: lowercase letters, digits and -, starting with a letter")
    present = {p.name for p in folder.iterdir()}
    for extra in sorted(present - FILES):
        say(f"{extra}: only provider.toml, meta.json, an icon and README.md belong here")
    check_icon(folder, present, say)
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
    problems += load_builtins()[1]
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


def enabled(meta):
    return meta.get("enabled", True) is True


NEWER = re.compile(r"this conch reads up to format")
BUILT_IN = re.compile(r"is a provider conch has built in")


def conch_check(conch="conch"):
    """conch sandbox provider check -offline on every sandbox provider. One
    that is off has no [ssh] by design, so conch's [ssh] problems are
    expected of it; anything else is a problem either way."""
    problems = []
    for folder in folders():
        _, meta, _ = load(folder)
        off = meta is not None and not enabled(meta)
        out = subprocess.run([conch, "sandbox", "provider", "check", "-offline", str(folder / "provider.toml")],
                             capture_output=True, text=True)
        said = [l.strip()[2:] for l in (out.stdout + out.stderr).splitlines() if l.strip().startswith("- ")]
        # A file newer than this conch reads (format 4: conch's own
        # providers as files) waits for a newer conch. Everything else this
        # conch says of it comes from reading it as an older format — keys
        # and placeholders it does not know yet — so none of it counts; the
        # registry's own checks still ran.
        newer = [p for p in said if NEWER.search(p)]
        if newer:
            print(f"::notice file=sandbox/{folder.name}/provider.toml::this conch does not read it yet: {newer[0]}")
            continue
        # Named for a provider this conch still has built in: that waits for
        # a conch without it, but the rest of what it says still counts.
        built_in = [p for p in said if BUILT_IN.search(p)]
        if built_in:
            print(f"::notice file=sandbox/{folder.name}/provider.toml::this conch does not read it yet: {built_in[0]}")
        said = [p for p in said if not BUILT_IN.search(p)]
        if out.returncode != 0 and not said and built_in:
            continue
        left = [p for p in said if not (off and p.startswith("[ssh]"))]
        if out.returncode != 0 and (not off or left or not said):
            problems += [f"{folder.name}: {p}" for p in left] or [f"{folder.name}: conch check failed: {(out.stdout + out.stderr).strip()}"]
    return problems


def load_builtins():
    """builtin.json's entries, and what is wrong with them."""
    if not BUILTIN.exists():
        return [], []
    problems = []
    try:
        items = json.loads(BUILTIN.read_text())
    except json.JSONDecodeError as e:
        return [], [f"builtin.json: {e}"]
    if not isinstance(items, list):
        return [], ["builtin.json: a list"]
    seen = set()
    for i, b in enumerate(items):
        at = f"builtin.json [{i}]"
        if not isinstance(b, dict):
            problems.append(f"{at}: an object")
            continue
        for k in sorted(set(b) - BUILTIN_KEYS):
            problems.append(f"{at}: unknown key {k}")
        if b.get("kind") not in BUILTIN_KINDS:
            problems.append(f"{at}: kind {b.get('kind')!r}: one of {sorted(BUILTIN_KINDS)}")
        if not NAME.match(str(b.get("name", ""))):
            problems.append(f"{at}: name {b.get('name')!r}")
        elif b["name"] in seen:
            problems.append(f"{at}: {b['name']} twice")
        seen.add(b.get("name"))
        if not b.get("label"):
            problems.append(f"{at}: no label")
        if urlparse(str(b.get("docs", ""))).scheme != "https":
            problems.append(f"{at}: docs: an https:// URL")
    names = {f.name for f in folders()} | {f.name for _, f in integration_folders()}
    for b in items:
        if isinstance(b, dict) and b.get("name") in names:
            problems.append(f"builtin.json: {b['name']} is also a file here; a name is one or the other")
    return items, problems


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
    legacy, entries, legacy_off, off = [], [], [], []
    for folder in folders():
        f, meta, problems = load(folder)
        if problems:
            raise SystemExit("\n".join(problems))
        raw = (folder / "provider.toml").read_bytes()
        (out / "providers" / f"{folder.name}.toml").write_bytes(raw)
        legacy_too = f.get("format", 1) in LEGACY_FORMATS
        if legacy_too:
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
        # Format 2 keeps format 1's fields for a sandbox provider, which
        # conch's sandbox installer reads, beside the ones every kind has.
        new = {**old, "kind": "sandbox", "version": 1, "hosts": {"api": api, "ssh": ssh_host},
               "tier": "verified" if meta.get("checked") else "community"}
        pic = icon(folder)
        if pic:
            # Served beside the index, and hashed as the file is.
            (out / "icons").mkdir(exist_ok=True)
            data = pic.read_bytes()
            path = f"icons/{folder.name}{pic.suffix}"
            (out / path).write_bytes(data)
            new.update(icon=path, icon_sha256=hashlib.sha256(data).hexdigest())
        if enabled(meta):
            if legacy_too:
                legacy.append(old)
            entries.append(new)
        else:
            # Off: listed apart, so no conch offers one it cannot reach.
            if legacy_too:
                legacy_off.append({**old, "enabled": False})
            off.append({**new, "enabled": False, "tier": "off"})
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
    builtins, problems = load_builtins()
    if problems:
        raise SystemExit("\n".join(problems))
    for b in builtins:
        entries.append({"kind": b["kind"], "name": b["name"], "label": b["label"], "builtin": True, "version": 0,
                        "hosts": {"api": ""}, "tier": "built in", "docs": b["docs"], "note": b.get("note", ""),
                        "key_env": b.get("key_env", "")})
    entries.sort(key=lambda e: (e["kind"], e["name"]))
    data = (json.dumps({"format": 2, "entries": entries, "disabled": off}, indent=2) + "\n").encode()
    (out / "index.json").write_bytes(data)
    (out / "legacy" / "index.json").write_text(json.dumps({"format": 1, "providers": legacy, "disabled": legacy_off}, indent=2) + "\n")
    key = os.environ.get("CONCH_REGISTRY_SIGNING_KEY", "").strip()
    if key:
        (out / "index.json.sig").write_text(sign(key, data) + "\n")
    pic = lambda e: f'<img src="{html.escape(e["icon"])}" alt="" width="20" height="20"> ' if e.get("icon") else ""
    rows = "\n".join(
        f"<tr><td>{pic(e)}{html.escape(e['label'])}</td><td>{html.escape(e['kind'])}</td><td><code>{html.escape(e['name'])}</code></td>"
        f"<td>{html.escape('built into conch' if e.get('builtin') else (e['hosts']['api'] or 'your own server'))}</td><td>{'checked ' + e['checked']['date'] if e.get('checked') else 'not checked live yet'}</td></tr>"
        for e in entries)
    rows += "".join(
        f"\n<tr><td>{pic(e)}{html.escape(e['label'])}</td><td>sandbox</td><td><code>{html.escape(e['name'])}</code></td>"
        f"<td>{html.escape(e['hosts']['api'])}</td><td>off: no ssh yet</td></tr>"
        for e in off)
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
    if len(argv) in (1, 2) and argv[0] == "conch-check":
        problems = conch_check(*argv[1:])
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    if len(argv) == 2 and argv[0] == "build":
        print(f"{len(build(argv[1]))} entries indexed")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
