"""What each entry can do, worked out from its file, and the JSON Schemas
the files are written against: python3 -m unittest discover -s scripts"""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import registry
from test_registry import CI, CI_META, GOOD, META

try:
    import jsonschema
except ImportError:  # the check workflow installs it; a laptop may not have it
    jsonschema = None

FULL = '''format = 3
name = "acme"
label = "Acme"
api = "https://api.acme.example"
key_env = "ACME_TOKEN"
auth_header = "X-API-Key"
auth_value = "{key}"

[create]
call = "POST /sandboxes"
body = { name = "{name}", spec = { cpus = "{cpu}", memory = "{memory_mb}" }, image = "{snapshot}", note = "made by conch" }
id = "id"

[get]
call = "GET /sandboxes/{id}"
state = "status"
name = "name"

[list]
call = "GET /sandboxes"
items = "items"
id = "id"
next = "next"
cursor_param = "cursor"
mine = "conch-"

[stop]
call = "POST /sandboxes/{id}/stop"

[delete]
call = "DELETE /sandboxes/{id}"

[states]
running = "started"
pending = "starting"
stopped = "stopped"
dead = "gone"

[ssh]
host = "{reply.host}"
user = "{reply.token}"
port = "{reply.port}"
key = "none"

[ssh.access]
call = "POST /sandboxes/{id}/ssh"
'''

FORMAT_4 = '''format = 4
name = "acme"
label = "Acme"
api = "https://api.acme.example"
key_env = "ACME_TOKEN"

[[setting]]
key = "region"
label = "Region"
choices = ["us", "eu"]

[size]
names = ["small", "large"]

[lifetime]
default_mins = 60
max_mins = 600

[create]
call = "POST /sandboxes?region={region}"
body = { name = "{name}", size = "{size}", ttl = "{ttl_secs}" }
id = "id"

[get]
call = "GET /sandboxes/{id}"
state = "status"
name = "name"

[list]
call = "GET /sandboxes"
items = "items"
id = "id"
all_mine = true

[start]
call = "POST /sandboxes/{id}/start"

[delete]
call = "DELETE /sandboxes/{id}"

[states]
up = "started"

[snapshot.save]
call = "POST /snapshots"
body = { sandbox = "{id}", name = "{snapshot_name}" }

[snapshot.list]
call = "GET /snapshots"
items = "snapshots"
name = "name"

[preview]
call = "GET /sandboxes/{id}/ports/{port}"
url = "url"

[usage]
call = "GET /sandboxes/{id}/usage?from={from}&to={to}"
cost = "dollars"

[ssh]
endpoint = "{reply.address}"
user = "root"
key = "authorize"
wait_secs = 60

[ssh.authorize]
call = "POST /sandboxes/{id}/keys"
body = { key = "{public_key}" }
'''


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for patch in (mock.patch.object(registry, "ROOT", self.root), mock.patch.object(registry, "PROVIDERS", self.root / "sandbox"),
                      mock.patch.object(registry, "BUILTIN", self.root / "builtin.json")):
            patch.start()
            self.addCleanup(patch.stop)

    def provider(self, toml, meta=META, name="acme"):
        folder = self.root / "sandbox" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "provider.toml").write_text(toml)
        (folder / "meta.json").write_text(json.dumps(meta))

    def integration(self, toml, kind="ci", name="acme-ci"):
        folder = self.root / kind / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "integration.toml").write_text(toml)
        (folder / "meta.json").write_text(json.dumps(CI_META))

    def index(self):
        self.assertEqual(registry.check(), [])
        site = self.root / "site"
        registry.build(site)
        return json.loads((site / "index.json").read_text())

    def entry(self, name):
        index = self.index()
        return next(e for e in index["entries"] + index["disabled"] if e["name"] == name)


class SandboxCapabilitiesTest(Isolated):
    def test_what_a_provider_can_do(self):
        self.provider(FULL)
        self.assertEqual(self.entry("acme")["capabilities"], {
            # In conch's order; start is missing, so there is nothing to resume with.
            "operations": ["create", "get", "list", "stop", "delete"],
            "ssh": {"key": "none", "access": True, "port": "reply"},
            # The placeholders the create body fills, nested ones too.
            "create": ["cpu", "memory_mb", "name", "snapshot"],
            "settings": [],
            "size": None,
            "lifetime": None,
            "states": ["gone", "started", "starting", "stopped"],
            "list": {"paged": True, "all_mine": False},
            "auth": {"type": "header", "header": "X-API-Key"},
            "needs": ["key"],
        })

    def test_format_4(self):
        self.provider(FORMAT_4)
        caps = self.entry("acme")["capabilities"]
        self.assertEqual(caps["operations"], ["create", "get", "list", "start", "delete",
                                              "snapshot_save", "snapshot_list", "preview", "usage"])
        self.assertEqual(caps["ssh"], {"key": "authorize", "access": False, "port": "endpoint"})
        self.assertEqual(caps["create"], ["name", "region", "size", "ttl_secs"])
        self.assertEqual((caps["settings"], caps["size"]), (["region"], "names"))
        # What the catalog can say before install: "1 h, at most 10 h".
        self.assertEqual(caps["lifetime"], {"default_mins": 60, "max_mins": 600})
        self.assertEqual(caps["list"], {"paged": False, "all_mine": True})
        self.assertEqual(caps["auth"], {"type": "header", "header": "Authorization"})

    def test_sizes(self):
        for size, want in (('[size]\ncpu = [1, 4]\n', "limits"),
                           ('[size.choices]\ncall = "GET /plans"\nitems = "plans"\ncpu = "cpu"\n', "plan")):
            with self.subTest(want=want):
                self.provider(FORMAT_4.replace('[size]\nnames = ["small", "large"]\n', size))
                self.assertEqual(self.entry("acme")["capabilities"]["size"], want)

    def test_a_provider_that_is_off_has_no_ssh(self):
        self.provider(GOOD.split("[ssh]")[0], meta={**META, "enabled": False})
        e = self.entry("acme")
        self.assertIsNone(e["capabilities"]["ssh"])
        # Said, not assumed: another reason may come.
        self.assertEqual(e["why"], "no ssh yet")

    def test_a_fixed_port(self):
        self.provider(FULL.replace('port = "{reply.port}"', "port = 2222"))
        self.assertEqual(self.entry("acme")["capabilities"]["ssh"]["port"], "fixed")


class IntegrationCapabilitiesTest(Isolated):
    def test_what_a_ci_integration_can_do(self):
        toml = CI.replace('follow_hosts = ["logs.acme.example"]\n', "").replace(
            "[runs]", '[auth]\ntype = "bearer"\n\n[detect]\nfiles = [".acme.yml"]\nchecks = ["acme/*"]\n\n'
                      '[states]\nok = "pass"\nbad = "fail"\nfine = "pass"\n\n[runs]')
        self.integration(toml)
        e = self.entry("acme-ci")
        self.assertEqual(e["capabilities"], {
            "operations": ["runs", "failed_log"],
            "auth": {"type": "bearer"},
            "needs": ["key"],
            "detect": ["checks", "files"],
            "detect_on": {"files": [".acme.yml"], "checks": ["acme/*"]},
            "states": ["fail", "pass"],
            "follow": False,
        })
        # The older field stays, for conches that read it.
        self.assertEqual(e["operations"], e["capabilities"]["operations"])

    def test_a_self_hosted_one_with_basic_auth(self):
        toml = CI.replace('api = "https://api.acme.example"', 'base_url = "ask"') \
                 .replace("[runs]", '[auth]\ntype = "basic"\nuser_env = "ACME_USER"\n\n[runs]')
        self.integration(toml)
        caps = self.entry("acme-ci")["capabilities"]
        self.assertEqual((caps["needs"], caps["auth"], caps["follow"]),
                         (["base_url", "key", "user"], {"type": "basic"}, True))

    def test_a_header_and_a_webhook(self):
        toml = CI.replace("[runs]", '[auth]\nheader = "Circle-Token"\nvalue = "{key}"\n\n[runs]')
        self.integration(toml)
        self.assertEqual(self.entry("acme-ci")["capabilities"]["auth"], {"type": "header", "header": "Circle-Token"})
        hook = ('format = 3\nkind = "notify"\nname = "hook"\nlabel = "Hook"\napi = "https://hooks.example"\n'
                'key_env = "HOOK_URL"\n\n[auth]\ntype = "url"\n\n[send]\ncall = "POST"\nbody = { text = "{title}" }\n')
        self.integration(hook, kind="notify", name="hook")
        caps = self.entry("hook")["capabilities"]
        self.assertEqual((caps["operations"], caps["auth"], caps["detect"], caps["states"]),
                         (["send"], {"type": "url"}, [], []))
        self.assertEqual(caps["detect_on"], {})

    def test_a_key_sent_the_way_a_sandbox_file_sends_it(self):
        # No [auth]: top-level auth_header and auth_value, as conch's
        # integration format also takes.
        self.integration(CI.replace('key_env = "ACME_TOKEN"', 'key_env = "ACME_TOKEN"\nauth_header = "X-Acme-Key"\nauth_value = "{key}"'))
        self.assertEqual(self.entry("acme-ci")["capabilities"]["auth"], {"type": "header", "header": "X-Acme-Key"})

    def test_a_tracker_that_lists_your_own(self):
        tracker = ('format = 3\nkind = "tickets"\nname = "acme-tickets"\nlabel = "Acme"\napi = "https://api.acme.example"\n'
                   'key_env = "ACME_TOKEN"\n\n[list]\ncall = "GET /t"\nitems = "t"\nkey = "id"\ntitle = "title"\n\n'
                   '[mine]\ncall = "GET /t?me=1"\nitems = "t"\nkey = "id"\ntitle = "title"\n\n'
                   '[get]\ncall = "GET /t/{ticket}"\nkey = "id"\ntitle = "title"\n')
        self.integration(tracker, kind="tickets", name="acme-tickets")
        e = self.entry("acme-tickets")
        self.assertEqual(e["capabilities"]["operations"], ["list", "mine", "get"])
        self.assertEqual(e["operations"], ["list", "mine", "get"])

    def test_the_shape_has_a_version(self):
        # 2: lifetime became its numbers; absent means 1.
        self.integration(CI)
        self.assertEqual(self.index()["capabilities_version"], 2)


class SchemaTest(unittest.TestCase):
    """schema/*.schema.json: what an editor checks a file against as it is
    typed, and what the build publishes beside the index."""

    def schema(self, name):
        return json.loads((registry.SCHEMAS / f"{name}.schema.json").read_text())

    def test_they_are_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry.build(Path(tmp))
            for name in ("provider", "integration"):
                self.assertEqual(json.loads((Path(tmp) / "schema" / f"{name}.schema.json").read_text()), self.schema(name))

    @unittest.skipUnless(jsonschema, "pip install jsonschema")
    def test_every_file_here_fits_its_schema(self):
        for name, files in (("provider", sorted(registry.PROVIDERS.glob("*/provider.toml"))),
                            ("integration", [p / "integration.toml" for _, p in registry.integration_folders()])):
            check = jsonschema.Draft202012Validator(self.schema(name))
            jsonschema.Draft202012Validator.check_schema(self.schema(name))
            self.assertTrue(files)
            for path in files:
                with self.subTest(path=str(path.relative_to(registry.ROOT))):
                    errors = [f"{'.'.join(map(str, e.absolute_path))}: {e.message}" for e in check.iter_errors(tomllib.loads(path.read_text()))]
                    self.assertEqual(errors, [])

    @unittest.skipUnless(jsonschema, "pip install jsonschema")
    def test_a_mistake_is_caught(self):
        provider = jsonschema.Draft202012Validator(self.schema("provider"))
        good = tomllib.loads(FULL)
        self.assertTrue(provider.is_valid(good))
        self.assertTrue(provider.is_valid(tomllib.loads(FORMAT_4)))
        for change in (
            lambda f: f.update(lable="Acme"),                     # a misspelt key
            lambda f: f["ssh"].update(hots="x"),                  # inside a table too
            lambda f: f["ssh"].update(key="password"),            # not one of conch's
            lambda f: f.update(format="3"),                       # a string, not a number
            lambda f: f["create"].update(call="FETCH /x"),        # not a method
            lambda f: f.update(api="http://api.acme.example"),    # https only
            lambda f: f["states"].update(sleeping="asleep"),      # not a state conch has
        ):
            f = tomllib.loads(FULL)
            change(f)
            self.assertFalse(provider.is_valid(f), f)
        integration = jsonschema.Draft202012Validator(self.schema("integration"))
        self.assertTrue(integration.is_valid(tomllib.loads(CI)))
        for change in (
            lambda f: f.pop("runs"),                              # ci needs runs
            lambda f: f.update(kind="chat"),                      # no such kind
            lambda f: f["runs"].update(cal="GET /x"),
            lambda f: f.update(auth={"type": "oauth"}),
        ):
            f = tomllib.loads(CI)
            change(f)
            self.assertFalse(integration.is_valid(f), f)


if __name__ == "__main__":
    unittest.main()
