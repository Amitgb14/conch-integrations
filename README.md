# conch integrations

Everything [conch](https://github.com/Amitgb14/conch) can talk to beyond
what it has built in, one folder per kind:

| Folder | Kind | Read by |
| --- | --- | --- |
| `sandbox/NAME/` | sandbox providers: cloud machines for agents | `conch sandbox provider …` |
| `ci/NAME/` | CI services: a branch's runs, a failed job's log, re-runs | `conch integration …`, `conch branch fix-ci` |
| `tickets/NAME/` | ticket trackers | `conch integration …`, the Tickets view |
| `notify/NAME/` | notifications | `conch integration …` |
| `host/NAME/` | code hosts (GitHub, built into conch) | the pull request view |

**The folders are the kinds.** conch lists a kind for each top-level
folder that holds an integration, in the order and with the names
[`kinds.json`](kinds.json) gives (a folder it does not name is listed
under its own name); a conch that has no code for a kind shows it as
needing a newer conch.

**Every folder has an icon** — `icon.svg` or `icon.png` (square, 64 px or
more, under 32 KB) — the service's own mark, which conch downloads, checks
against the index's hash and draws on its card. It may not run anything
or reach outside the file. The built-ins in [`builtin.json`](builtin.json)
(GitHub, Linear, Jira…) have a folder under their kind with their icon
alone. Logos are their owners' trademarks, shown to name the service.

Each is a file describing a service's HTTP API — which call does what,
where the answer is in the reply, how the key is sent — with a
`meta.json` saying who wrote it and when it was last checked live. conch
runs any such file with one reader of its own; nothing here is code, and
a file's key goes only to the hosts it names.

The list as conch reads it is published, signed, at
<https://amitgb14.github.io/conch-integrations/index.json>. This
repository was conch-sandbox-providers; conches from before the move read
the sandbox providers at the old address, which
[Amitgb14/conch-sandbox-providers](https://github.com/Amitgb14/conch-sandbox-providers)
mirrors from `legacy/` here.

## Integrations

```sh
conch integration search ci
conch integration info circleci
conch integration install circleci
```

| Integration | Kind | Live check |
| --- | --- | --- |
| Bitbucket Pipelines | ci | not yet |
| Buildkite | ci | not yet |
| CircleCI | ci | not yet |
| GitLab CI | ci | not yet |
| Jenkins | ci | not yet |
| Semaphore | ci | not yet |
| GitLab issues | tickets | not yet |
| Shortcut | tickets | not yet |
| Discord | notify | not yet |
| ntfy | notify | not yet |
| Slack | notify | not yet |

Built into conch, and listed here (`builtin.json`) so the catalog is one
place: GitHub, GitHub Actions, GitHub Issues, Linear and Jira. They have no
file: conch's own code runs them.

An integration's `meta.json` has a `version`, one more with every change
and never reused, and may list `revoked` versions with the reason; conch
stops using a revoked version and says why.

## Sandbox providers

| Provider | Name | Live check |
| --- | --- | --- |
| Agent37 | `agent37` | off: no ssh yet |
| Archil | `archil` | off: no ssh yet |
| boat.dev | `boat` | not yet |
| briq | `briq` | off: no ssh yet |
| CreateOS | `createos` | off: no ssh yet |
| Daytona | `daytona` | not yet |
| DigitalOcean | `digitalocean` | not yet |
| Freestyle | `freestyle` | off: no ssh yet |
| Gravix Layer | `gravixlayer` | off: no ssh yet |
| Hetzner Cloud | `hetzner` | not yet |
| InstaBox | `instabox` | 2026-11-15 |
| kosa8 Cloud | `kosa8` | off: no ssh yet |
| Microsandbox | `microsandbox` | off: no ssh yet |
| MIOSA | `miosa` | off: no ssh yet |
| Mosaic Sandbox | `mosaic` | not yet |
| Namespace | `namespace` | not yet |
| Promigence | `promigence` | off: no ssh yet |
| Tensorlake | `tensorlake` | not yet |
| Uno | `uno` | off: no ssh yet |

Daytona, boat.dev and Tensorlake were built into conch until they became
files here (format 4: what a person can choose for them — a region, a
default image, a size — and their snapshots and preview links). A conch
from before that keeps its own and reads only `legacy/`, which leaves
format-4 files out.

A provider marked **off** has an API conch can drive but no plain-ssh way
into its sandboxes. Its file describes the API in full and leaves `[ssh]`
out, and its `meta.json` says `"enabled": false`. conch cloud will reach
such sandboxes through a public URL; until then both indexes list them under
`disabled`, apart from the providers conch offers, so no conch installs one
it cannot connect to. A setting in conch will turn them on.

### Looked at, and why they are not here

A provider needs an HTTP API that a provider file can describe; lacking
only plain ssh, it is listed off. These, from the
[ComputeSDK sandbox ratings](https://www.computesdk.com/benchmarks/sandboxes/ratings)
(November 2026), cannot be described yet, even off.

| Provider | What stops it |
| --- | --- |
| E2B | its list is a bare JSON array, which `[list] items` cannot name; ssh only through a websocket proxy |
| Novita | no documented HTTP API; ssh only through a websocket proxy, as E2B |
| Modal | no HTTP API: its SDKs and CLI only |
| Vercel Sandbox | stop takes a session id, every other call the sandbox's name; no ssh |
| Blaxel | standby and resume are called on each sandbox's own host, not the API's; no ssh |
| Beam | its VMs take ssh, but are made only through its CLI and SDK |
| CodeSandbox | a sandbox has no state field; no ssh, only a websocket agent |
| Cloudflare Sandbox | no hosted API: it is a Workers binding, with no ssh |
| Upstash Box | ssh fits, but the HTTP API is undocumented and its list is a bare array |
| Isorun | a run takes no name, and its list is undocumented; no ssh |
| Superserve | its list is a bare JSON array; no ssh, only exec, files and preview ports |
| Arker | no stop or start call: a VM only idles; its ssh would otherwise fit |
| Buddy Works | every path holds the person's workspace, which a shared file cannot; its ssh would otherwise fit (format 3) |
| Sail | create needs the organisation's app_id, fetched by another call; ssh by short-lived certificate |
| Sandbox0 | a sandbox has no name, label or metadata to find conch's by; its ssh gateway would fit |
| Tenki | no documented HTTP API (Connect calls only in its SDK's code); ssh through its CLI |
| SFCompute | GPU instances on bought capacity: pool, image and sku per account, and terminate is final |
| Google Cloud Run | no API: sandboxes are started inside your own Cloud Run container |

### Using one

```sh
conch sandbox provider search
conch sandbox provider install hetzner
export HCLOUD_TOKEN=…          # or put the key in Settings → Sandboxes
conch sandbox -provider hetzner create
```

Install shows the hosts the file sends your key and your ssh connections
to, and asks before it saves anything. It checks the file's hash against
the index. `conch sandbox provider update` takes newer versions of what you
installed from here, leaves a file you have edited alone, and asks again
when a provider's hosts change.

### Adding one

Have conch adapt the provider from its API docs, check it with your key,
and publish it:

```sh
conch sandbox adapt https://docs.example.com/api
conch sandbox provider publish example
```

`publish` opens a pull request here (through your fork, unless you can push
to this repository) with `sandbox/NAME/provider.toml` and a `meta.json`
saying who adapted it, from which docs, and when your key last listed
sandboxes with it. Your key is never part of it.

A provider's folder may also hold its icon, `icon.svg` or `icon.png`,
taken from the provider's own website. conch and the published list draw
it beside the provider's name.

By hand, a pull request needs the same two files; the format is in
[conch's guide](https://github.com/Amitgb14/conch/blob/master/internal/sandbox/providerfile.md).

## What each one can do

Every entry in `index.json` carries `capabilities`, worked out from its
file when the index is built — never written by hand, so it cannot
disagree with the file. A sandbox provider's:

```json
"capabilities": {
  "operations": ["create", "get", "list", "start", "stop", "delete"],
  "ssh": {"key": "none", "access": true, "port": "reply"},
  "create": ["cpu", "memory_mb", "name", "snapshot"],
  "settings": ["region"], "size": "limits", "lifetime": false,
  "states": ["error", "gone", "started", "starting", "stopped", "stopping"],
  "list": {"paged": true, "all_mine": false},
  "auth": {"type": "header", "header": "X-API-Key"},
  "needs": ["key"]
}
```

- `operations`: the calls the file has, in conch's order; format 4 adds
  `snapshot_save`, `snapshot_list`, `snapshot_forget`, `preview`, `usage`
- `ssh`: whose key opens it (`account`, `authorize`, `none`), whether conch
  asks `[ssh.access]` first, and whether the port is `fixed`, read from the
  `reply` or given with the host as an `endpoint`; `null` for one that is off
- `create`: the placeholders the create call fills, so conch asks only for
  what the provider takes
- `settings`, `size` (`names`, `limits`, the `plan`'s, or `null`),
  `lifetime`: format 4's choices
- `states`: the states of conch's the provider can report
- `needs`: what the person supplies — `key`, and for an integration a
  `base_url` (self-hosted) or a `user` (basic auth)

An integration's has `operations` (also kept at the top of its entry, for
older conches), `auth`, `needs`, `detect` (how conch recognises a project
that uses it), `states` and `follow` (whether it fetches from
`follow_hosts`). A built-in has none: conch's own code runs it.

### Schemas

`schema/provider.schema.json` and `schema/integration.schema.json` are
JSON Schemas of the two files, published beside the index
(`https://amitgb14.github.io/conch-integrations/schema/…`). Point an
editor's TOML extension at them to see a misspelt key or a state conch
does not have as you type. They catch the shape; conch's own check is
still the final word.

## What is checked

On every pull request:

- conch's own check of the file (`conch sandbox provider check -offline`),
  where a sandbox provider that is off may lack only its `[ssh]`
- a sandbox provider's `meta.json` `enabled` agrees with its file: off
  exactly when there is no `[ssh]`
- the folder holds only `provider.toml`, `meta.json`, an optional icon
  and an optional `README.md`, and the names agree
- an icon is a plain picture: an SVG with no script, event handler or
  reference outside the file, or a square PNG at least 64px across; 32 KB
  at most
- nothing that looks like a key, token or password is committed
- a provider already here keeps its API and ssh hosts. A file sends
  everybody's API key to its `api` host, so moving it is a maintainer's
  decision, given with the `host-change` label

Every pull request is reviewed by a maintainer before it is merged. That
review is what stands between a file and everybody's key, so read the
hosts first.

## Running the checks

```sh
pip install jsonschema                        # optional: checks every file against schema/
python3 -m unittest discover -s scripts       # Python 3.11+
python3 scripts/registry.py check --base origin/main
python3 scripts/registry.py conch-check        # needs conch on PATH
python3 scripts/registry.py build _site
```

Licensed under Apache-2.0, as conch is.
