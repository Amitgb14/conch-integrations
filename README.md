# conch integrations

Everything [conch](https://github.com/Amitgb14/conch) can talk to beyond
what it has built in, one folder per kind:

| Folder | Kind | Read by |
| --- | --- | --- |
| `sandbox/NAME/` | sandbox providers: cloud machines for agents | `conch sandbox provider …` |
| `ci/NAME/` | CI services: a branch's runs, a failed job's log, re-runs | `conch integration …`, `conch branch fix-ci` |
| `tickets/NAME/` | ticket trackers | `conch integration …`, the Tickets view |
| `notify/NAME/` | notifications | `conch integration …` |
| `deploy/NAME/` | deploy previews: a branch's preview links, failed builds, releases | `conch integration …` (a conch with deploy previews) |
| `import/NAME/` | other apps whose conversations conch brings in, read on this machine | Integrations → Import, `conch import` |
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
a file's key goes only to the hosts it names. An import file is the
exception: it has no key and no API, only where an app keeps its data on
this machine (see [Import](#import)).

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
| Netlify | deploy | not yet |
| Vercel | deploy | not yet |
| Conductor | import | not yet |

Built into conch, and listed here (`builtin.json`) so the catalog is one
place: GitHub, GitHub Actions, GitHub Issues, Linear and Jira. They have no
file: conch's own code runs them.

An integration's `meta.json` has a `version`, one more with every change
and never reused, and may list `revoked` versions with the reason; conch
stops using a revoked version and says why.

## Deploy previews

`deploy/NAME/integration.toml` is an integration file (format 3) of kind
`deploy`: where a branch is built and shown. The person connects their
account with a token; conch finds the project or site by the repository
it builds from, shows each branch's preview link, sends a failed build's
log to the branch's agent as it does a failed CI run, and releases a ready
deploy to production when the person asks.

| Operation | | conch asks it | placeholders |
| --- | --- | --- | --- |
| `previews` | required | a branch's deploys, newest first, at `{head}` when there is one | `{branch}`, `{head}`, the remote's parts |
| `failed_log` | optional | what a failed build printed: the end goes to the agent | `{deploy}` |
| `redeploy` | optional | build a deploy again | `{deploy}` |
| `promote` | optional | release a deploy to production; conch asks first | `{deploy}` |

A deploy's fields are a run's (`items`, `id`, `name`, `state`, `url` — the
preview's address — `commit`, `started`, `finished`) and three more:
`environment` (production, preview…), `error` (why it failed) and
`inspect` (the service's page for it). `[states]` maps every state the
API documents to `ready`, `building`, `failed` or `canceled`.

| Service | Finds the project by | Release | Failed log |
| --- | --- | --- | --- |
| Vercel | the project linked to the repository's URL | builds the deploy again for production, as "Promote to Production" does: a preview's environment variables never reach production | the build's events |
| Netlify | the site whose repository is the remote's path | publishes the deploy as it was built ("Publish deploy"); a deploy preview is a draft and cannot be published | the deploy's error message: Netlify's API has no build log |

conch reads the kind from a release with deploy previews; until then it
lists Deploy previews as needing a newer conch, and `conch integration
check` does not know these files, so CI checks them with the registry's
own checks and the schema only.

## Import

An import file says where another app keeps its conversations on this
machine, so conch can bring them in — each resuming in its own agent — and
nothing more:

```toml
[source]
platforms = ["darwin"]
store = "sqlite"               # sqlite, jsonl or json
path = "~/Library/Application Support/com.conductor.app/conductor.db"
reader = "conductor"           # the reader in conch that understands it
min_reader = 1                 # the reader version this file was checked with
```

The store is only ever read, and only on this machine: an import file has
no `key_env`, no `api` and no operations, so nothing in it can send
anything anywhere. `path` (and `[detect] files`) start with `~/` and hold
no `..`. `reader` names code in conch, the way a CI file's operations
name conch's contract: the file cannot add a reader, only point at one. A
conch without that reader, or with an older version of it than
`min_reader`, shows the card as needing a newer conch. The index entry
carries `platforms`, `reader` and `min_reader`, and its capabilities say
`needs: []`.

Conductor is the first: its conversations and workspaces, from its own
database on a Mac. Its icon is a plain stand-in until Conductor's own mark
replaces it.

## Sandbox providers

| Provider | Name | Live check |
| --- | --- | --- |
| Agent37 | `agent37` | off: no ssh yet |
| Amika | `amika` | off: no ssh yet |
| Archil | `archil` | off: no ssh yet |
| Blaxel | `blaxel` | off: no ssh yet |
| boat.dev | `boat` | not yet |
| briq | `briq` | off: no ssh yet |
| CreateOS | `createos` | off: no ssh yet |
| Daytona | `daytona` | not yet |
| DigitalOcean | `digitalocean` | not yet |
| E2B | `e2b` | off: no ssh yet |
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
| Superserve | `superserve` | off: no ssh yet |
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
| Novita | no documented HTTP API for its sandboxes (SDK and CLI only); ssh only through a websocket proxy, as E2B |
| Modal | no HTTP API: its SDKs and CLI only; and a finished sandbox cannot be started again |
| Vercel Sandbox | stop takes a session id, every other call the sandbox's name; no ssh |
| Beam | its VMs take ssh, but are made only through its CLI, SDK and dashboard; its HTTP API has pods, with no start and no ssh |
| CodeSandbox | a sandbox has no state field; no ssh, only a websocket agent |
| Cloudflare Sandbox | no hosted API: a Workers binding, or a bridge Worker in your own account (no list, start or stop); no ssh |
| Upstash Box | ssh fits, but the HTTP API is undocumented |
| Isorun | a run takes no name or label, and its list's reply is undocumented; no ssh |
| Arker | no stop or start call: a VM only idles; its ssh would otherwise fit |
| Buddy Works | every path holds the person's workspace, which a shared file cannot; its ssh would otherwise fit (format 3) |
| Sail (Sail Research) | create needs the organisation's app_id, looked up on another host; ssh by short-lived certificate |
| Sandbox0 | a sandbox has no name, label or metadata to find conch's by; its ssh gateway would fit |
| Tenki (Luxor Agent Cloud) | no HTTP API: SDKs over Connect/gRPC, with the id in the body; ssh through its CLI |
| SFCompute | GPU instances on bought capacity: pool, image and sku per account; no stop or start, and terminate is final |
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
  "settings": ["region"], "size": "limits", "lifetime": null,
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
  `lifetime` (`{default_mins, max_mins}`, or `null`): format 4's choices
- `states`: the states of conch's the provider can report
- `needs`: what the person supplies — `key`, and for an integration a
  `base_url` (self-hosted) or a `user` (basic auth)

An integration's has `operations` (also kept at the top of its entry, for
older conches), `auth` (from `[auth]`, else a top-level `auth_header`),
`needs`, `detect` (which ways conch recognises a project that uses it) and
`detect_on` (what those match: `{"files": [".circleci/config.yml"]}`),
`states` and `follow` (whether it fetches from `follow_hosts`). A built-in
has none: conch's own code runs it.

A provider listed under `disabled` says `why` (`"no ssh yet"`).
`capabilities_version` at the top of the index goes up when a field
changes meaning, not when one is added; absent is 1, where `lifetime` was
true or false.

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
- an import file has no key, API or operations, its `[source]` store is
  `sqlite`, `jsonl` or `json`, and its paths start with `~/` with no `..`
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
