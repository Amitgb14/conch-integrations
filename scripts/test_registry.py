"""Tests for registry.py: python3 -m unittest discover -s scripts"""

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import registry

GOOD = '''format = 2
name = "acme"
label = "Acme"
api = "https://api.acme.example"
key_env = "ACME_TOKEN"

[ssh]
host = "{reply.server.ip}"
user = "root"
'''

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path fill="#000" d="M0 0h32v32H0z"/></svg>'


def png(width, height):
    """Enough of a PNG for the checker: the signature and an IHDR."""
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", zlib.crc32(chunk))


META = {"adapted_by":"claude", "adapted": "2026-11-08", "docs": "https://docs.acme.example/api",
        "conch": "0.1.10", "checked": None}


class RegistryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.providers = self.root / "sandbox"
        for patch in (mock.patch.object(registry, "ROOT", self.root), mock.patch.object(registry, "PROVIDERS", self.providers),
                      mock.patch.object(registry, "BUILTIN", self.root / "builtin.json")):
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, name="acme", toml=GOOD, meta=None, extra=None):
        folder = self.providers / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "provider.toml").write_text(toml.replace('name = "acme"', f'name = "{name}"'))
        (folder / "meta.json").write_text(json.dumps(META if meta is None else meta))
        for file, text in (extra or {}).items():
            (folder / file).write_text(text)
        return folder

    def problems(self, base=None):
        return "\n".join(registry.check(base))

    def test_a_good_provider(self):
        self.write()
        self.assertEqual(self.problems(), "")

    def test_an_empty_registry(self):
        self.assertEqual(self.problems(), "")
        self.providers.mkdir()
        self.assertEqual(registry.build(self.root / "site"), [])
        self.assertEqual(json.loads((self.root / "site" / "index.json").read_text()), {"format": 2, "entries": [], "disabled": []})
        self.assertEqual(json.loads((self.root / "site" / "legacy" / "index.json").read_text()), {"format": 1, "providers": [], "disabled": []})

    def test_the_folder(self):
        for name, want in (("Acme", "the folder's name"), ("a", "the folder's name")):
            with self.subTest(name=name):
                folder = self.write(name)
                self.assertIn(want, self.problems())
                for p in folder.iterdir():
                    p.unlink()
                folder.rmdir()
        self.write(extra={"run.sh": "curl evil"})
        self.assertIn("run.sh: only provider.toml", self.problems())
        (self.providers / "acme" / "run.sh").unlink()
        (self.providers / "acme" / "meta.json").unlink()
        self.assertIn("no meta.json", self.problems())
        (self.providers / "stray.toml").write_text("")
        self.assertIn("stray.toml: sandbox/ holds a folder", self.problems())

    def test_the_file(self):
        for change, want in (
            (('name = "acme"', 'name = "other"'), "the folder is 'acme'"),
            (("format = 2", "format = 5"), "format 5"),
            (("https://api.acme.example", "http://api.acme.example"), "https://"),
            (("https://api.acme.example", "https://localhost"), "not this computer"),
            (("[ssh]", "[ssh"), "provider.toml:"),
        ):
            with self.subTest(want=want):
                folder = self.providers / "acme"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "provider.toml").write_text(GOOD.replace(*change))
                (folder / "meta.json").write_text(json.dumps(META))
                self.assertIn(want, self.problems())
        (self.providers / "acme" / "provider.toml").write_bytes(b"#" * (registry.MAX_BYTES + 1))
        self.assertIn("over 256 KB", self.problems())

    def test_meta(self):
        for meta, want in (
            ({**META, "extra": 1}, "unknown key extra"),
            ({k: v for k, v in META.items() if k != "docs"}, "no docs"),
            ({**META, "adapted": "yesterday"}, "adapted: YYYY-MM-DD"),
            ({**META, "conch": "latest"}, "meta.json conch"),
            ({**META, "checked": "yes"}, "null, or"),
            ({**META, "checked": {"date": "2026-11-08", "conch": "0.1.10", "sandboxes": -1}}, "how many"),
            ({**META, "checked": {"date": "2026-11-08", "conch": "0.1.10", "sandboxes": 0, "key": "x"}}, "unknown key key"),
            ([], "an object"),
        ):
            with self.subTest(want=want):
                self.write(meta=meta)
                self.assertIn(want, self.problems())
        self.write(meta={**META, "checked": {"date": "2026-11-08", "conch": "0.1.10", "sandboxes": 3}})
        self.assertEqual(self.problems(), "")
        (self.providers / "acme" / "meta.json").write_text("{")
        self.assertIn("meta.json:", self.problems())

    def test_secrets(self):
        for line in (
            'auth_value = "Bearer dop_v1_0123456789abcdef0123"',
            'token = "hunter2hunter2"',
            'note = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA me@host"',
            'note = "-----BEGIN OPENSSH PRIVATE KEY-----"',
            'note = "' + "a1B2" * 12 + '"',
        ):
            with self.subTest(line=line):
                self.write(toml=GOOD.replace('key_env = "ACME_TOKEN"', 'key_env = "ACME_TOKEN"\n' + line))
                self.assertIn("looks like", self.problems())
        # Placeholders, URLs and comments are not secrets.
        self.write(toml=GOOD.replace('key_env = "ACME_TOKEN"', 'key_env = "ACME_TOKEN"\nauth_value = "Bearer {key}"\n'
                                     'docs = "https://docs.acme.example/' + "x" * 60 + '"\n# token = "not-a-secret-at-all"'))
        self.assertEqual(self.problems(), "")

    def test_a_host_change_needs_a_label(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.write()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=self.root, check=True, env=env)
        self.assertEqual(self.problems("main"), "")
        for change in (("api.acme.example", "api.evil.example"), ("{reply.server.ip}", "gw.evil.example")):
            with self.subTest(change=change):
                self.write(toml=GOOD.replace(*change))
                self.assertIn("host-change", self.problems("main"))
                with mock.patch.dict(os.environ, {"ALLOW_HOST_CHANGE": "true"}):
                    self.assertEqual(self.problems("main"), "")
        # A new provider has no hosts to move from.
        self.write("newone", toml=GOOD.replace("api.acme.example", "api.new.example"))
        self.write()
        self.assertEqual(self.problems("main"), "")

    def test_format4_kept_from_legacy(self):
        # Format 4 is conch's own providers as files (settings, sizes,
        # snapshots): accepted here, and left out of legacy/, whose readers
        # are released conches that refuse it — and that have those
        # providers built in.
        self.write()
        self.write("newer", toml=GOOD.replace("format = 2", "format = 4").replace('name = "acme"', 'name = "newer"'))
        self.assertEqual(self.problems(), "")
        site = self.root / "site"
        entries = registry.build(site)
        self.assertEqual([(e["name"], e["format"]) for e in entries], [("acme", 2), ("newer", 4)])
        legacy = json.loads((site / "legacy" / "index.json").read_text())
        self.assertEqual([p["name"] for p in legacy["providers"]], ["acme"])
        self.assertFalse((site / "legacy" / "providers" / "newer.toml").exists())
        self.write("newest", toml=GOOD.replace("format = 2", "format = 5").replace('name = "acme"', 'name = "newest"'))
        self.assertIn("format 5", self.problems())

    def test_build(self):
        self.write()
        self.write("beta", meta={**META, "checked": {"date": "2026-11-08", "conch": "0.1.10", "sandboxes": 1}})
        site = self.root / "site"
        entries = registry.build(site)
        self.assertEqual([e["name"] for e in entries], ["acme", "beta"])
        index = json.loads((site / "index.json").read_text())
        self.assertEqual(index["format"], 2)
        acme = index["entries"][0]
        self.assertEqual((acme["kind"], acme["hosts"]), ("sandbox", {"api": "api.acme.example", "ssh": "{reply.server.ip}"}))
        # Conches from before the move read the sandbox providers in format
        # 1, from legacy/, which the old address mirrors.
        legacy = json.loads((site / "legacy" / "index.json").read_text())
        self.assertEqual((legacy["format"], [p["name"] for p in legacy["providers"]]), (1, ["acme", "beta"]))
        self.assertEqual((site / "legacy" / "providers" / "acme.toml").read_bytes(), (self.providers / "acme" / "provider.toml").read_bytes())
        raw = (site / "providers" / "acme.toml").read_bytes()
        self.assertEqual(raw, (self.providers / "acme" / "provider.toml").read_bytes())
        import hashlib
        self.assertEqual(acme["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual((acme["api_host"], acme["ssh_host"], acme["format"], acme["file"]),
                         ("api.acme.example", "{reply.server.ip}", 2, "providers/acme.toml"))
        self.assertIn("not checked live yet", (site / "index.html").read_text())
        self.assertIn("checked 2026-11-08", (site / "index.html").read_text())
        # A bad provider stops the build rather than publishing it.
        self.write("gamma", meta={})
        with self.assertRaises(SystemExit):
            registry.build(self.root / "site2")

    def test_an_icon(self):
        # The provider's own icon, from its website: icon.svg or icon.png.
        folder = self.write(extra={"icon.svg": SVG})
        self.assertEqual(self.problems(), "")
        site = self.root / "site"
        registry.build(site)
        acme = json.loads((site / "index.json").read_text())["entries"][0]
        import hashlib
        self.assertEqual((acme["icon"], acme["icon_sha256"]), ("icons/acme.svg", hashlib.sha256(SVG.encode()).hexdigest()))
        self.assertEqual((site / "icons" / "acme.svg").read_text(), SVG)
        self.assertIn('<img src="icons/acme.svg"', (site / "index.html").read_text())
        (folder / "icon.svg").unlink()
        (folder / "icon.png").write_bytes(png(64, 64))
        self.assertEqual(self.problems(), "")
        self.assertEqual(json.loads((registry.build(site) and site / "index.json").read_text())["entries"][0]["icon"], "icons/acme.png")
        (folder / "icon.png").unlink()
        # Without one the provider is still listed, with no icon.
        self.assertEqual(self.problems(), "")
        self.assertNotIn("icon", registry.build(self.root / "site3")[0])

    def test_a_bad_icon(self):
        # An icon is shown in conch and on the site, so it may not run or
        # fetch anything: no script, no handler, no outside reference.
        bad_svgs = (
            (SVG.replace("<path", "<script>alert(1)</script><path"), "script"),
            (SVG.replace("<path", '<path onload="alert(1)"'), "onload"),
            (SVG.replace("<path", '<image href="https://evil.example/x.png"/><path'), "href"),
            (SVG.replace("<path", '<foreignObject><p>hi</p></foreignObject><path'), "foreignObject"),
            (SVG.replace("<path", '<style>@import url(https://evil.example/a.css);</style><path'), "outside"),
            (SVG.replace("<path", '<path style="fill:url(https://evil.example/#a)"'), "outside"),
            ('<!DOCTYPE svg [<!ENTITY a "aaaa">]>' + SVG, "DOCTYPE"),
            ("<html/>", "an <svg>"),
            ("<svg", "icon.svg:"),
            (SVG.replace("</svg>", "<!--" + "x" * (40 << 10) + "--></svg>"), "over 32 KB"),
        )
        for svg, want in bad_svgs:
            with self.subTest(want=want):
                self.write(extra={"icon.svg": svg})
                self.assertIn(want, self.problems())
        (self.providers / "acme" / "icon.svg").write_text(SVG)
        (self.providers / "acme" / "icon.png").write_bytes(png(64, 64))
        self.assertIn("icon.svg or icon.png, not both", self.problems())
        (self.providers / "acme" / "icon.svg").unlink()
        for raw, want in ((b"GIF89a", "not a PNG"), (png(64, 32), "square"), (png(16, 16), "at least 64")):
            with self.subTest(want=want):
                (self.providers / "acme" / "icon.png").write_bytes(raw)
                self.assertIn(want, self.problems())

    def test_format_3(self):
        # A port read from [ssh.access]'s reply, and headers: conch's format 3.
        self.write(toml=GOOD.replace("format = 2", "format = 3"))
        self.assertEqual(self.problems(), "")

    def test_a_provider_without_ssh_is_off(self):
        # Its API is described; its [ssh] waits for conch cloud's public URL.
        no_ssh = GOOD.split("[ssh]")[0] + "# [ssh]\n# host = ...\n"
        off = {**META, "enabled": False}
        self.write("dark", toml=no_ssh, meta=off)
        self.assertEqual(self.problems(), "")
        for toml, meta, want in (
            (GOOD, off, "has [ssh]"),
            (no_ssh, META, "no [ssh]"),
            (no_ssh, {**off, "enabled": "no"}, "enabled: true or false"),
        ):
            with self.subTest(want=want):
                self.write("dark", toml=toml, meta=meta)
                self.assertIn(want, self.problems())
        # Off is listed apart in both indexes: no conch offers one it cannot reach.
        self.write("dark", toml=no_ssh, meta=off)
        self.write()
        site = self.root / "site"
        self.assertEqual([e["name"] for e in registry.build(site)], ["acme"])
        index = json.loads((site / "index.json").read_text())
        self.assertEqual([e["name"] for e in index["entries"]], ["acme"])
        self.assertEqual([(e["name"], e["enabled"]) for e in index["disabled"]], [("dark", False)])
        legacy = json.loads((site / "legacy" / "index.json").read_text())
        self.assertEqual([e["name"] for e in legacy["providers"]], ["acme"])
        self.assertEqual([e["name"] for e in legacy["disabled"]], ["dark"])
        self.assertTrue((site / "providers" / "dark.toml").exists())
        self.assertIn("off: no ssh yet", (site / "index.html").read_text())

    def test_conch_check(self):
        no_ssh = GOOD.split("[ssh]")[0]
        self.write("dark", toml=no_ssh, meta={**META, "enabled": False})
        self.write()
        ssh_only = "x:\n  - [ssh] host and user: no ssh\n  - [ssh] key \"\": account, authorize or none\n"

        def run(outputs):
            calls = []

            def fake(cmd, **kw):
                calls.append(cmd[-1])
                rc, err = outputs[Path(cmd[-1]).parent.name]
                return subprocess.CompletedProcess(cmd, rc, "", err)
            with mock.patch.object(registry.subprocess, "run", fake):
                return registry.conch_check("conch"), calls

        problems, calls = run({"acme": (0, ""), "dark": (1, ssh_only)})
        self.assertEqual(problems, [])
        self.assertEqual(len(calls), 2)
        # Anything beyond the missing [ssh] is still a problem, on or off.
        problems, _ = run({"acme": (0, ""), "dark": (1, ssh_only + "  - [states] maps nothing to started\n")})
        self.assertIn("[states]", "\n".join(problems))
        problems, _ = run({"acme": (1, ssh_only), "dark": (1, ssh_only)})
        self.assertEqual([p.split(":")[0] for p in problems], ["acme", "acme"])
        # A file newer than the conch checking it (format 4, conch's own
        # providers as files) or named for a provider that conch still has
        # built in waits for a newer conch: not a problem, but said.
        newer = "x:\n  - format 4: this conch reads up to format 3; update conch to use it\n"
        builtin = "x:\n  - name \"daytona\" is a provider conch has built in\n"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            problems, _ = run({"acme": (1, newer), "dark": (1, builtin + ssh_only)})
        self.assertEqual(problems, [])
        self.assertEqual(out.getvalue().count("::notice"), 2)
        problems, _ = run({"acme": (1, newer + "  - [states] maps nothing to started\n"), "dark": (0, "")})
        self.assertIn("[states]", "\n".join(problems))


CI = '''format = 3
kind = "ci"
name = "acme-ci"
label = "Acme CI"
api = "https://api.acme.example"
key_env = "ACME_TOKEN"
follow_hosts = ["logs.acme.example"]

[runs]
call = "GET /runs?branch={branch}"

[failed_log]
call = "GET /runs/{run}/log"
text = "."
'''

CI_META = {"version": 1, "adapted_by": "claude", "adapted": "2026-11-15", "docs": "https://docs.acme.example/api",
           "conch": "0.2.1", "checked": None}


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for patch in (mock.patch.object(registry, "ROOT", self.root), mock.patch.object(registry, "PROVIDERS", self.root / "sandbox"),
                      mock.patch.object(registry, "BUILTIN", self.root / "builtin.json")):
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, name="acme-ci", toml=CI, meta=None, kind="ci", extra=None):
        folder = self.root / kind / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "integration.toml").write_text(toml.replace('name = "acme-ci"', f'name = "{name}"'))
        (folder / "meta.json").write_text(json.dumps(CI_META if meta is None else meta))
        for file, text in (extra or {}).items():
            (folder / file).write_text(text)
        return folder

    def problems(self, base=None):
        return "\n".join(registry.check(base))

    def test_a_good_integration(self):
        self.write()
        self.assertEqual(self.problems(), "")

    def test_the_file_and_meta(self):
        for toml, meta, want in (
            (CI.replace('kind = "ci"', 'kind = "notify"'), None, "kind 'notify'; it is in ci/"),
            (CI.replace("format = 3", "format = 2"), None, "format = 3"),
            (CI.replace('name = "acme-ci"', 'name = "other"'), None, "the folder is 'acme-ci'"),
            (CI.replace("https://api.acme.example", "http://api.acme.example"), None, "api: an https"),
            (CI, {**CI_META, "version": 0}, "version: 1"),
            (CI, {k: v for k, v in CI_META.items() if k != "conch"}, "no conch"),
            (CI, {**CI_META, "revoked": [{"version": 1}]}, "revoked: a list"),
            (CI, {**CI_META, "checked": {"date": "2026-11-15", "conch": "x"}}, "checked.conch"),
            (CI.replace('key_env = "ACME_TOKEN"', 'key_env = "ACME_TOKEN"\nnote = "ghp_abcdefghijklmnop1234"'), None, "looks like an API token"),
        ):
            with self.subTest(want=want):
                self.write(toml=toml, meta=meta)
                self.assertIn(want, self.problems())
        self.write(extra={"run.sh": "x"})
        self.assertIn("run.sh: only integration.toml", self.problems())

    def test_a_self_hosted_one_has_no_api(self):
        self.write(toml=CI.replace('api = "https://api.acme.example"', 'base_url = "ask"'))
        self.assertEqual(self.problems(), "")

    def test_a_host_change_needs_a_label(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        self.write()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=self.root, check=True, env=env)
        for change in (("api.acme.example", "api.evil.example"), ('["logs.acme.example"]', '["logs.acme.example", "cdn.evil.example"]')):
            with self.subTest(change=change):
                self.write(toml=CI.replace(*change))
                self.assertIn("host-change", self.problems("main"))
                with mock.patch.dict(os.environ, {"ALLOW_HOST_CHANGE": "true"}):
                    self.assertEqual(self.problems("main"), "")

    def test_build(self):
        self.write()
        self.write("old-ci", meta={**CI_META, "version": 3, "revoked": [{"version": 3, "reason": "sent logs elsewhere"}],
                                    "checked": {"date": "2026-11-15", "conch": "0.2.1", "detail": "12 runs read"}})
        site = self.root / "site"
        registry.build(site)
        index = json.loads((site / "index.json").read_text())
        by = {e["name"]: e for e in index["entries"]}
        acme = by["acme-ci"]
        self.assertEqual((acme["kind"], acme["version"], acme["file"], acme["hosts"], acme["key_env"], acme["operations"], acme["tier"]),
                         ("ci", 1, "integrations/acme-ci.toml", {"api": "api.acme.example", "follow": ["logs.acme.example"]},
                          "ACME_TOKEN", ["runs", "failed_log"], "community"))
        import hashlib
        self.assertEqual(acme["sha256"], hashlib.sha256((site / "integrations" / "acme-ci.toml").read_bytes()).hexdigest())
        self.assertEqual((by["old-ci"]["tier"], by["old-ci"]["revoked"][0]["reason"]), ("verified", "sent logs elsewhere"))
        self.assertFalse((site / "index.json.sig").exists())
        # A bad one stops the build rather than publishing it.
        self.write("bad-ci", meta={})
        with self.assertRaises(SystemExit):
            registry.build(self.root / "site2")

    def test_builtins(self):
        self.write()
        (self.root / "builtin.json").write_text(json.dumps([
            {"kind": "tickets", "name": "jira", "label": "Jira", "docs": "https://developer.atlassian.com", "key_env": "JIRA_API_TOKEN"},
            {"kind": "host", "name": "github", "label": "GitHub", "docs": "https://cli.github.com"}]))
        self.assertEqual(self.problems(), "")
        registry.build(self.root / "site")
        by = {e["name"]: e for e in json.loads((self.root / "site" / "index.json").read_text())["entries"]}
        self.assertEqual((by["jira"]["builtin"], by["jira"]["kind"], by["jira"]["tier"], by["jira"]["key_env"]), (True, "tickets", "built in", "JIRA_API_TOKEN"))
        self.assertNotIn("file", by["jira"])
        self.assertIn("built into conch", (self.root / "site" / "index.html").read_text())
        for items, want in (
            ([{"kind": "repo", "name": "x1", "label": "X", "docs": "https://x"}], "kind 'repo'"),
            ([{"kind": "host", "name": "acme-ci", "label": "X", "docs": "https://x"}], "also a file here"),
            ([{"kind": "host", "name": "gh", "label": "X", "docs": "https://x", "file": "x"}], "unknown key file"),
            ([{"kind": "host", "name": "gh", "label": "X", "docs": "http://x"}], "docs: an https"),
            ([{"kind": "host", "name": "gh", "label": "X", "docs": "https://x"}] * 2, "gh twice"),
            ({}, "a list"),
        ):
            with self.subTest(want=want):
                (self.root / "builtin.json").write_text(json.dumps(items))
                self.assertIn(want, self.problems())
        (self.root / "builtin.json").write_text("[")
        self.assertIn("builtin.json:", self.problems())

    def test_signing(self):
        import base64
        self.write()
        seed = os.urandom(32)
        with mock.patch.dict(os.environ, {"CONCH_REGISTRY_SIGNING_KEY": base64.b64encode(seed).decode()}):
            registry.build(self.root / "site")
        sig = base64.b64decode((self.root / "site" / "index.json.sig").read_text())
        self.assertEqual(len(sig), 64)
        # openssl checks it with the public half, as conch does.
        key = self.root / "key.der"
        key.write_bytes(registry._ED25519_PREFIX + seed)
        pub = self.root / "pub.pem"
        subprocess.run(["openssl", "pkey", "-inform", "DER", "-in", str(key), "-pubout", "-out", str(pub)], check=True)
        (self.root / "sig").write_bytes(sig)
        ok = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pub), "-rawin",
                             "-in", str(self.root / "site" / "index.json"), "-sigfile", str(self.root / "sig")], capture_output=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        with mock.patch.dict(os.environ, {"CONCH_REGISTRY_SIGNING_KEY": "short"}):
            with self.assertRaises(SystemExit):
                registry.build(self.root / "site3")


class RepositoryTest(unittest.TestCase):
    """The providers committed here, rather than ones made up for a test."""

    def test_the_providers_here_are_good(self):
        self.assertEqual(registry.check(), [])

    def test_instabox_sends_the_headers_its_api_requires(self):
        # Mutating POSTs and DELETEs need an Idempotency-Key, and a machine
        # delete names the machine in X-Confirm-Delete, or InstaBox answers
        # 409 (https://instabox.sh/docs/api-reference/introduction.md).
        f = tomllib.loads((registry.PROVIDERS / "instabox" / "provider.toml").read_text())
        self.assertEqual(f.get("format"), 3)
        top = f.get("headers", {}).get("Idempotency-Key")
        for call in ("create", "start", "stop", "delete"):
            self.assertEqual(f[call].get("headers", {}).get("Idempotency-Key", top), "{uuid}", call)
        self.assertEqual(f["ssh"]["access"].get("headers", {}).get("Idempotency-Key", top), "{uuid}", "ssh.access")
        for call in ("get", "list"):
            self.assertIn(f[call].get("headers", {}).get("Idempotency-Key", top), (None, ""), call)
        self.assertEqual(f["delete"]["headers"]["X-Confirm-Delete"], "{id}")

    def test_every_provider_here_has_its_icon(self):
        for folder in registry.folders():
            self.assertTrue({"icon.svg", "icon.png"} & {p.name for p in folder.iterdir()}, folder.name)

    def test_the_readme_lists_every_provider(self):
        # Rows of the README's sandbox table: | Label | `name` | live check |
        readme = (registry.ROOT / "README.md").read_text()
        listed = {}
        for label, name, live in re.findall(r"^\| ([^|]+?) \| `([a-z0-9-]+)` \| ([^|]+?) \|$", readme, re.M):
            listed[name] = (label, live)
        self.assertEqual(sorted(listed), [f.name for f in registry.folders()])
        for folder in registry.folders():
            f = tomllib.loads((folder / "provider.toml").read_text())
            meta = json.loads((folder / "meta.json").read_text())
            live = meta["checked"]["date"] if meta["checked"] else "not yet"
            want = (f.get("label") or folder.name, live if meta.get("enabled", True) else "off: no ssh yet")
            self.assertEqual(listed[folder.name], want, folder.name)


if __name__ == "__main__":
    unittest.main()
