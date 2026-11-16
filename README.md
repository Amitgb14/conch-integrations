# conch integrations

Everything [conch](https://github.com/Amitgb14/conch) can talk to beyond
what it has built in, one folder per kind:

| Folder | Kind | Read by |
| --- | --- | --- |
| `sandbox/NAME/` | sandbox providers: cloud machines for agents | `conch sandbox provider …` |
| `ci/NAME/` | CI services: a branch's runs, a failed job's log, re-runs | `conch integration …`, `conch branch fix-ci` |
| `tickets/NAME/` | ticket trackers | `conch integration …`, the Tickets view |
| `notify/NAME/` | notifications | `conch integration …` |

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
| Daytona | `daytona` | not yet |
| DigitalOcean | `digitalocean` | not yet |
| Hetzner Cloud | `hetzner` | not yet |
| InstaBox | `instabox` | 2026-11-15 |
| Tensorlake | `tensorlake` | not yet |

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

By hand, a pull request needs the same two files; the format is in
[conch's guide](https://github.com/Amitgb14/conch/blob/master/internal/sandbox/providerfile.md).

## What is checked

On every pull request:

- conch's own check of the file (`conch sandbox provider check -offline`)
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
python3 scripts/registry.py build _site
```

Licensed under Apache-2.0, as conch is.
