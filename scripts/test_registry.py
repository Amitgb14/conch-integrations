"""Tests for registry.py: python3 -m unittest discover -s scripts"""

import json
import os
import subprocess
import tempfile
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

META = {"adapted_by": "claude", "adapted": "2026-11-08", "docs": "https://docs.acme.example/api",
        "conch": "0.1.10", "checked": None}


class RegistryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.providers = self.root / "providers"
        for patch in (mock.patch.object(registry, "ROOT", self.root), mock.patch.object(registry, "PROVIDERS", self.providers)):
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
        self.assertEqual(json.loads((self.root / "site" / "index.json").read_text()), {"format": 1, "providers": []})

    def test_the_folder(self):
        for name, want in (("Acme", "the folder's name"), ("daytona", "built in"), ("a", "the folder's name")):
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
        self.assertIn("stray.toml: providers/ holds a folder", self.problems())

    def test_the_file(self):
        for change, want in (
            (('name = "acme"', 'name = "other"'), "the folder is 'acme'"),
            (("format = 2", "format = 3"), "format 3"),
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

    def test_build(self):
        self.write()
        self.write("beta", meta={**META, "checked": {"date": "2026-11-08", "conch": "0.1.10", "sandboxes": 1}})
        site = self.root / "site"
        entries = registry.build(site)
        self.assertEqual([e["name"] for e in entries], ["acme", "beta"])
        index = json.loads((site / "index.json").read_text())
        acme = index["providers"][0]
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


if __name__ == "__main__":
    unittest.main()
