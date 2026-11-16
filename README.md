# conch sandbox providers

Sandbox providers for [conch](https://github.com/Amitgb14/conch) beyond the
ones it has built in. Each is a provider file: a description of which calls
of the provider's API make, look at, list, start, stop and delete a sandbox,
how its states read, and how ssh gets in. conch runs any such file with one
reader of its own; nothing here is code.

| Provider | Name | Live check |
| --- | --- | --- |
| Agent37 | `agent37` | off: no ssh yet |
| briq | `briq` | off: no ssh yet |
| CreateOS | `createos` | off: no ssh yet |
| DigitalOcean | `digitalocean` | not yet |
| Freestyle | `freestyle` | off: no ssh yet |
| Gravix Layer | `gravixlayer` | off: no ssh yet |
| Hetzner Cloud | `hetzner` | not yet |
| InstaBox | `instabox` | checked 2026-11-15 |
| kosa8 Cloud | `kosa8` | off: no ssh yet |
| Microsandbox | `microsandbox` | off: no ssh yet |
| MIOSA | `miosa` | off: no ssh yet |
| Namespace | `namespace` | not yet |
| Promigence | `promigence` | off: no ssh yet |
| Uno | `uno` | off: no ssh yet |

The list as conch reads it is published at
<https://amitgb14.github.io/conch-sandbox-providers/index.json>.

A provider marked **off** has an API conch can drive but no plain-ssh way
into its sandboxes. Its file describes the API in full and leaves `[ssh]`
out, and its `meta.json` says `"enabled": false`. conch cloud will reach
such sandboxes through a public URL; until then the index lists them under
`disabled`, apart from the providers conch offers, so no conch installs one
it cannot connect to. A setting in conch will turn them on.

## Looked at, and why they are not here

A provider needs an HTTP API that a provider file can describe; lacking
only plain ssh, it is listed off. These, from the
[ComputeSDK sandbox ratings](https://www.computesdk.com/benchmarks/sandboxes/ratings)
(November 2026), cannot be described yet, even off. Daytona and Tensorlake
are not listed because conch has them built in.

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

## Using one

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

## Adding one

Have conch adapt the provider from its API docs, check it with your key,
and publish it:

```sh
conch sandbox adapt https://docs.example.com/api
conch sandbox provider publish example
```

`publish` opens a pull request here (through your fork, unless you can push
to this repository) with `providers/NAME/provider.toml` and a `meta.json`
saying who adapted it, from which docs, and when your key last listed
sandboxes with it. Your key is never part of it.

By hand, a pull request needs the same two files; the format is in
[conch's guide](https://github.com/Amitgb14/conch/blob/master/internal/sandbox/providerfile.md).

## What is checked

On every pull request:

- conch's own check of the file (`conch sandbox provider check -offline`),
  where a provider that is off may lack only its `[ssh]`
- `meta.json`'s `enabled` agrees with the file: off exactly when there is
  no `[ssh]`
- the folder holds only `provider.toml`, `meta.json` and an optional
  `README.md`, and the names agree
- nothing that looks like a key, token or password is committed
- a provider already here keeps its API and ssh hosts. A file sends
  everybody's API key to its `api` host, so moving it is a maintainer's
  decision, given with the `host-change` label

Every pull request is reviewed by a maintainer before it is merged. That
review is what stands between a file and everybody's key, so read the
hosts first.

## Running the checks

```sh
python3 -m unittest discover -s scripts       # Python 3.11+
python3 scripts/registry.py check --base origin/main
python3 scripts/registry.py conch-check        # needs conch on PATH
python3 scripts/registry.py build _site
```

Licensed under Apache-2.0, as conch is.
