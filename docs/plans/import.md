# Plan: import, a new kind — Conductor first

Conductor (conductor.build) joined Meta. Conductor Cloud went read-only
on 2026-11-13 and shuts down on **2026-11-20**; sign-ups and downloads
stopped on 2026-11-04. Its users have their workspaces (git worktrees,
which conch already reads) and their **conversations**, which Conductor
kept in a database of its own. This plan brings those conversations into
conch so each one **resumes in its own agent**, and does it from
Conch.app.

- **Mock:** https://claude.ai/artifact/WT9vbg7rY491yE61EKDqWA — four
  screens: Integrations → Import (the one way in), choose what comes
  over, imported, Sessions.
- **Already built** (conch PR #261, branch `conch/docs-from-conductor`):
  `sessions.ReadConductor` reads Conductor's database, and
  `conch import conductor` writes each conversation as a Markdown handoff.
  This plan builds on it; nothing there is thrown away.

Two repositories change. **This one** gets the kind and the Conductor
entry; **conch** gets the code that reads and writes. As everywhere in
this registry, the file describes and conch's own code acts: no code
comes from here.

## What we know about Conductor's data

Read from a real database (Conductor with Claude Code 2.1.201 and Codex
0.144.1 in `agent-binaries/`):

- **Where:** `~/Library/Application Support/com.conductor.app/conductor.db`
  (SQLite, write-ahead log). Mac only. Removed with the app.
- **`repos`:** `id, name, root_path, default_branch, setup_script,
  run_script, archive_script, conductor_config, …` — `root_path` is the
  user's own clone or one Conductor made under `~/conductor/repos/NAME`.
- **`workspaces`:** `id, repository_id, directory_name, branch, state
  (ready | archived), workspace_path, sandbox_provider, …` —
  `workspace_path` is `~/conductor/workspaces/REPO/CITY`, a git worktree
  of `root_path`; gone once archived or deleted.
- **`sessions`:** `id, workspace_id, agent_type (claude | codex | …),
  title (default 'Untitled'), claude_session_id, model, permission_mode,
  created_at, updated_at, …` — `claude_session_id` names a Claude Code
  session **whose file is not on disk**: Conductor did not leave it in
  `~/.claude/projects`. So the database is the only copy.
- **`session_messages`:** `id, session_id, role, content, created_at,
  sdk_message_id, turn_id, …`. A `user` row's `content` is the prompt as
  typed. An `assistant` row's `content` is one Claude Agent SDK stream
  message as JSON, complete:
  - `{"type":"assistant","uuid","session_id","parent_tool_use_id","message":{"id","model","role","content":[text | thinking | tool_use],"usage",…}}`
  - `{"type":"user","uuid","session_id","timestamp","parent_tool_use_id","tool_use_result","message":{"role":"user","content":[tool_result]}}`
  - `{"type":"system","subtype":"init" | "task_progress" | …}`, `{"type":"result",…}`
- **Codex** sessions (`agent_type = 'codex'`): no sample yet. The reader
  takes `{"type":"item.completed","item":{"type":"agent_message","text"}}`
  as a guess; **get a real Codex conversation from a Conductor user
  before relying on it** (open question 1).

The stream holds every tool call and result with its `uuid`, which is
what a resumable Claude Code session needs.

## Part 1 — this repository

1. **`kinds.json`**: add, after `notify`:
   `{"kind": "import", "label": "Import", "about": "other apps whose conversations conch can bring in"}`.
   A conch that has no code for `import` shows it as needing a newer
   conch, as for any new kind.
2. **`import/conductor/integration.toml`** — what conch needs to find and
   read Conductor, and nothing it could run:

   ```toml
   format = 3
   kind = "import"
   name = "conductor"
   label = "Conductor"
   docs = "https://www.conductor.build/docs"
   adapted_by = "claude"
   adapted = "2026-11-16"
   note = "Conductor's conversations and workspaces, from its own database on this Mac. Conductor Cloud workspaces must be moved to the Mac in Conductor first."

   [source]
   platforms = ["darwin"]
   store = "sqlite"
   path = "~/Library/Application Support/com.conductor.app/conductor.db"
   reader = "conductor"          # the reader in conch that understands it
   min_reader = 1                # the reader version this file was checked with

   [detect]
   files = ["~/Library/Application Support/com.conductor.app/conductor.db"]
   ```

   `reader` names code in conch, the way a ci file's operations name
   conch's contract: the file cannot add a reader, only point at one.
   `path` is only ever read, and only on this machine.
3. **`import/conductor/meta.json`** (`version: 1`, `conch: "0.2.2"` or
   the release that ships the reader, `checked: null` until a live check)
   and **`icon.svg`** (Conductor's mark; logos are their owners' marks,
   shown to name the service, as the README says).
4. **`schema/integration.schema.json`**: `kind` gains `"import"`; an
   import file needs no `key_env` and no `api` (make `required` depend on
   kind with `if/then`), and has `source` (`platforms`, `store` ∈
   {`sqlite`, `jsonl`, `json`}, `path`, `reader`, `min_reader`) instead of
   operations. Paths are `~/`-relative, never absolute to a user, never
   `..`.
5. **`scripts/registry.py`**: `OPERATIONS["import"] = ()`; an import file
   is valid without `key_env`; `source.path` must start with `~/` and
   hold no `..`; the index entry carries `needs: []`, `platforms`,
   `reader` and `min_reader`; `INTEGRATION_FILES` unchanged.
   **Tests** (`scripts/test_registry.py`): the Conductor folder passes; an
   import file with `key_env`, an absolute or `..` path, an unknown
   `store`, or operations, fails with a message naming the field.
6. **`README.md`**: `import/NAME/` in the folder table, Conductor in the
   integrations table, and a short "Import" section (what it reads, that
   nothing leaves the machine).

Ship this part **after** conch's reader is released, or behind
`min_reader`: an older conch must show the card as needing a newer conch,
not fail to read the index (check that against conch's index parser).

## Part 2 — conch (the contract this repository depends on)

### Read

`sessions.ReadConductor` (built) is the `conductor` reader, version 1.
Keep: reading from a copy of the database and its `-wal`/`-shm`, never
the original; the fallback query for older schemas; `Imported` with
`Session`, `Repo`, `Root`, `Workspace`, `Turns`, `Unread`. Add the raw
stream messages to `Imported` (`Messages []json.RawMessage` with role and
time), which the writers need and the Markdown handoff does not.

### Write, so it resumes

A writer per agent, behind one interface:

```go
type SessionWriter interface {
    Agent() string                       // "claude", "codex"
    Write(ctx, im Imported, dir string) (agentSessionID string, path string, err error)
}
```

**Claude Code** — one JSONL file at
`~/.claude/projects/<dir with / and . as ->/<new uuid>.jsonl`
(or `$CLAUDE_CONFIG_DIR/projects/…`), where `dir` is the workspace if it
is still there, else the repository root. One line per message, chained:

| Conductor row | Line written |
| --- | --- |
| `user`, plain text | `{"type":"user","message":{"role":"user","content":TEXT},…}` |
| `assistant`, SDK `type:"assistant"` | `{"type":"assistant","message":<its message>,"requestId":…}` |
| `assistant`, SDK `type:"user"` (tool results) | `{"type":"user","message":<its message>,"toolUseResult":<tool_use_result>}` |
| `system`, `result`, progress | not written |

Every line also gets `uuid` (the SDK's, else a new one), `parentUuid`
(the line before), `sessionId` (the new id), `timestamp` (the row's,
RFC 3339), `cwd` (`dir`), `gitBranch` (the workspace's branch),
`isSidechain: false`, `userType: "external"`, `version` (the Claude Code
version found, else `2.1.201`, the one Conductor shipped), and
`entrypoint: "conch-import"`. A final `{"type":"ai-title","aiTitle":TITLE}`
line names it. Messages with `parent_tool_use_id` set belong to a
subagent: write them with `isSidechain: true`.

**Prove it before building on it:** a test with a fixture database, then
`claude --resume <id> -p "say ok"` against the written file in a scratch
`CLAUDE_CONFIG_DIR` (skipped without `claude`), checking it loads with
its history. If Claude Code refuses a written file, fall back to the
Markdown handoff for that conversation and say so — never a half-written
session.

**Codex** — a rollout file at
`~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<uuid>.jsonl` (or
`$CODEX_HOME`): a `session_meta` line (`id`, `cwd`, `cli_version`,
`originator: "conch-import"`, `git`), then `response_item` lines of
`type:"message"` with `role` user/assistant and `input_text`/`output_text`
parts. Text only until we have real Codex rows from Conductor (open
question 1); same `codex resume <id>` check as above.

### Once, and again later

`$CONCH_HOME/imports/conductor/state.json` maps Conductor's session id to
`{agent, agentSessionID, path, lastMessageID, importedAt, size}`.
Importing again:

- a new conversation is written;
- one with new messages in Conductor gets them **only if the agent's file
  is unchanged since import** (same size); if the person carried on in
  conch, it is left alone and reported as "carried on in conch";
- nothing is ever deleted.

### Server, so the app and the TUI share it

Two protocol methods, served by the server (the app never reads the
database itself):

- `import.scan {source}` → the list the sheet shows: per conversation
  `id, title, agent, messages, repo, branch, workspaceState (on disk |
  removed | cloud), lastUsed, alreadyImported`, plus which repositories
  conch does not have as projects. Cheap: counts, not transcripts.
- `import.run {source, ids, resumable, addProjects, markdown}` → per
  conversation `ok | skipped (why) | failed (why)`, the agent session id
  and path, streamed as progress for a long import.

`conch import conductor` becomes a client of the same two, with
`-resumable` on by default and `-markdown` for today's handoff files.

### Conch.app (the mock)

One way in: **Integrations → Import**. No sidebar card, no File menu
item.

1. **Import** — a kind in the Integrations window. When `[detect] files`
   exists, the kind says **1 found** and the Conductor card says "Found on
   this Mac · 12 conversations in 5 workspaces", with the warning
   "Conductor Cloud shuts down on Nov 20. Move cloud workspaces to this
   Mac in Conductor first, then import. The conversations go when
   Conductor is removed." Below it: what it reads, what it brings in,
   what it leaves out, its version and when it was checked. **Import…**
   opens the sheet. Without Conductor on the Mac the card says *not found
   on this Mac* and Import… is off.
2. **Choose** — a sheet from `import.scan`, grouped by workspace, each
   with its state: *worktree on disk*, *worktree removed · resumes in the
   repository*, *new project*, *in Conductor Cloud* (disabled, "transfer
   it to your Mac in Conductor first"). Options: make each resumable (on),
   add missing repositories as projects (on), also save a readable copy
   (off). Footer: "11 of 12 conversations · 1 is still in Conductor
   Cloud", **Import 11**.
3. **Imported** — per conversation ✓ resumable / ! resumes in the
   repository / ✕ not imported (why), each with **Resume**; "Importing
   again later brings in only what is new"; **Open Sessions**.
4. **Sessions** — imported sessions are ordinary sessions of their agent,
   with a *from Conductor* badge and a **From Conductor** filter (the
   server knows them from `state.json`).

The TUI gets the same through `conch import` and a line in the Sessions
view; no new screens there in this round.

### Projects

"Add the repositories conch doesn't have" adds `repos.root_path` with
`project.add`. A root under `~/conductor/repos/` is Conductor's own
clone: add it as it is (its worktrees are there) and say where it is.

## Tests (conch)

As conch's AGENTS.md requires — every one isolated in `t.TempDir()`, with
`HOME`, `CONCH_HOME`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME` set there:

- reader: done (fixture database, older schema, write-ahead log,
  unreadable rows, cancelled context, original unchanged).
- Claude writer: line chain (`parentUuid`), tool use and result kept and
  paired, sidechain messages, cwd encoding (spaces, dots, unicode), the
  workspace gone → repository, the file parses as Claude Code's own
  reader in `internal/sessions` reads it, and it **lists in
  `sessions.List`** for that folder.
- Codex writer: the same, read back by `codexTranscript`.
- state: import twice → nothing new; a new message → appended; the agent
  file changed → left alone and reported; state from an older conch loads.
- server: `import.scan` and `import.run` with a fake source; an old
  server lacking them → the app says to update.
- app (`macos/Tests`): the sheet's model — grouping, disabled cloud rows,
  the count in the button.

## Order

1. **Now (before 2026-11-20):** merge PR #261 — the Markdown handoff
   works today and is in the migration guide.
2. Claude writer + `state.json` + `conch import conductor -resumable`,
   with the `claude --resume` proof. Update the guide: "resumes in Claude
   Code".
3. This repository: the `import` kind and `import/conductor` (Part 1):
   the app's only way in is its card, so it comes before the app flow.
4. `import.scan` / `import.run` and the Conch.app flow (screens 1–4).
5. Codex writer, once open question 1 is answered.

## Open questions

1. What do Codex conversations look like in Conductor's database? Ask a
   Conductor user for one `session_messages` row of a Codex session
   (content redacted), or install Conductor and run one.
2. Does Claude Code accept a transcript it did not write? Step 2's proof
   answers it; if a field is required that we lack, it shows there.
3. Conductor Cloud workspaces, after "transfer to local": do their
   messages land in the local database? Test with a cloud workspace
   before the 20th, if anyone still has one.
4. Cursor and OpenCode sessions in Conductor (`agent_type`): none seen;
   until then they import as Markdown only.
5. Is a second source worth the kind now (Cursor's chat history, Claude
   Desktop)? The kind is built for it; nothing in this plan depends on it.
