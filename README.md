# RimWorld mod development workspace

This workspace diagnoses RimWorld issues and develops independent patches, forks,
and new mods. It supports **RimWorld 1.7 only**. Each directory under `projects/`
is its own Git repository and has a plain-language `PURPOSE.md`.

For a fresh checkout, start with [Building mods with the shared tooling](docs/building.md).
Clone mod repositories independently into `projects/<key>/`; any direct child
with `mod.toml` is discovered automatically. Mods are not submodules and are not
included in the tooling repository. The tooling is MIT licensed; each mod keeps
its own license. `workspace.example.json` documents the required local paths.

Public repositories: [shared tooling](https://github.com/eiennohito/rimworld-mods)
and [KanbanStockpile-Refilled](https://github.com/eiennohito/rimworld-kanbanstockpile-refilled).

This README is the owner’s local workspace guide. Project READMEs and Workshop
descriptions are for players; AGENTS.md files contain instructions for coding
agents. [Documentation audiences](docs/documentation.md) defines what belongs
in each, including public developer docs and owner-specific maintainer notes.

| Project | What it does |
| --- | --- |
| [Refilled](projects/kanban-refilled/PURPOSE.md) | Keeps storage supplied while reducing unnecessary hauling |
| [CISE Automation](projects/cise-automation/PURPOSE.md) | Applies visible, editable packing plans to caravans and transports |
| [Colony Groups](projects/colony-groups/PURPOSE.md) | Keeps home groups and off-map expeditions visible, including separate colony and ship homes |
| [Better Pawn Control: Away](projects/bpc-away/PURPOSE.md) | Carries individual expedition timetables from permanent homes to new temporary maps |
| [Pen Grazing](projects/pen-grazing/PURPOSE.md) | Graphs pen vegetation and grazing balance using one shared sampling budget |
| [Local Compatibility Fixes](projects/local-compat/PURPOSE.md) | Local hauling, inventory and mod compatibility fixes for 1.7 |
| [Mining Yield Priorities](projects/mining-yield-priorities/PURPOSE.md) | Sends the best-yield miners to valuable tiles and other miners to cheaper tiles |
| [Compositable Loadouts: Slots](projects/compositable-slots/PURPOSE.md) | Filters apparel by slot, reserves empty space, and equips Away tags before departure |
| [Crew Presets — Local Fork](projects/crew-presets/PURPOSE.md) | Saved crews for gravship launches, including pilot, copilot and other launch roles |
| [Genepack Trade Details](projects/genepack-trade/PURPOSE.md) | Full gene tooltips in trade and good/bad/mixed genepack grouping |
| [Surgery Browser](projects/surgery-browser/PURPOSE.md) | Collapsible surgery families and compact body-part actions in Nice Health Tab |
| [Sink mode](projects/sink-mode/PURPOSE.md) | Starts workbench bills when allowed ingredient stock exceeds a chosen threshold |
| [Hospitality: Word of Mouth](projects/word-of-mouth/PURPOSE.md) | Hospitality guests bring more silver after liked stays, expect more, spend it in your shop, and judge rent against per-guest impressiveness |

The old Kanban compatibility patch is fully superseded by Refilled. Its repository
is retained under `archive/projects/kanban-compat/`, outside the active project list.

## Everyday commands

Python orchestration is a `uv` project in `tools/`; C# belongs in mod code,
project-specific runtime fixtures, and the few shared .NET inspection/host helpers.
The wrapper selects the locked Python environment and workspace-local caches.

```sh
tools/rw list
tools/rw check                              # fast infrastructure checks; no game
tools/rw build colony-groups                # compile + clean unpacked package
tools/rw latest colony-groups               # print the persistent package path
tools/rw test colony-groups --suite runtime # headless game/patch inspection
tools/rw test colony-groups --suite ui      # LAST RESORT: a specific UI/scenario question
tools/rw sync                               # show status and offer to build/update mods
tools/rw install colony-groups --dry-run    # optional installation preview
tools/rw install colony-groups              # install into RimSort's local folder
tools/rw publish kanban-refilled --dry-run   # prepare a SteamCMD upload for review
```

`rw test` defaults to a headless runtime suite. It is game-backed, not a pure
unit test, and still pays the engine startup cost. Inspect, compile and use
lightweight checks first; prefer targeted headless checks for basic behavior.
Batch related assertions into one launch. `rw check` runs the fast Python
infrastructure tests without launching RimWorld.

Generated-colony/full-engine scenarios and UI runs are **last resorts** for a
specific question lighter/headless tests cannot answer. They are not a routine
step after every edit, and passing headless checks do not need repeating in a
rendered scenario without a new reason. Use the smallest sufficient check and
report what it establishes and what remains untested.

`rw install PROJECT` installs into the chosen RimSort instance's local mod
folder, with rollback backups. It never changes the active mod list. Installation
and activation are separate actions. Use `--dry-run` for an optional preview.
Builds do not create ZIP archives or upload to Steam.

## Directory ownership

| Directory | Purpose and lifetime |
| --- | --- |
| `projects/` | Editable mod repositories, their own tests, content and purpose documents; durable |
| `investigations/` | Diagnosis notes and recorded findings before/alongside mod development; durable authored material |
| `tools/` | Shared `uv` tooling, tests, templates and .NET helpers; durable source |
| `references/` | Read-only links to the game, Workshop, RimSort and player data |
| `outputs/mods/` | Built, unpacked mod packages for installation; **never automatically cleaned** |
| `outputs/reports/` | Reports deliberately saved for review; **never automatically cleaned** |
| `sessions/` | Compiler output, test hosts, saves, logs, captures and decompilations; **seven-day retention**, unless pinned |
| `state/` | Build pointers, installation receipts/backups and migration records; durable |
| `.cache/` | Reusable tools/dependencies and rebuildable caches; explicit cache cleanup only |
| `archive/` | Historical source/tool snapshots and old user-facing packages; retained for deliberate review/removal |
| `docs/` | Shared workspace rules and operating instructions |

See [the cleanup lifecycle](docs/lifecycle.md) and
[game test instructions](docs/running-rimworld.md). Session scratch never shares a
directory with built mods intended for installation.

## Development workflow

Start by investigating the issue. For substantive diagnoses, keep a short current
summary under `investigations/<issue>/`: symptom, findings and open questions.
Routine fixes need no new report. The outcome may
be finding an existing mod, making a separate patch mod, forking an upstream mod,
or creating a new mod. Only the latter three need a project repository.

A project declares its build, content, dependencies and test suites in `mod.toml`.
Build and installation mechanics belong in shared tooling, not new per-mod scripts.
Runtime fixtures live in that project's `tests/`, not in the shared harness.
New projects can start from `tools/templates/mod.toml`; write `PURPOSE.md` before
implementation. Explain the intended player behavior and current limits plainly.

Follow the [documentation audience rules](docs/documentation.md). Keep player
instructions, owner release work and agent directives in their assigned files.
Developer docs record implementation details, source evidence, initialization
costs, recurring work and the limits of validation. Public copy uses player
vocabulary and makes only claims supported by that evidence.

For two sessions editing the same mod, use a Git worktree inside this workspace
and pass `--worktree PATH` to build/test/install. Reference properties are supplied
by the shared build command, so worktrees need no copied build scripts. Different
mods and independent test runs can run concurrently. Packages are immutable
snapshots; a later build cannot change an already-running instance's mods.

## Provenance and safety

`workspace.json` holds machine paths. `tools/rw setup` checks the links and 1.7
version; `tools/rw inventory` refreshes cached Workshop metadata when needed.
`build.json` identifies the package and source revision. Build reuse uses file
size and modification time to notice source/reference updates; this is a local
cache, not a dependency lock or reproducibility guarantee. Installation checks
package identity and uses the latest built package without rejecting older game
or mod records. Build first when you want current source changes included.

Game runs use copied hosts with Steam initialization disabled. A sandbox-only
engine copy forces audio into its supported no-device mode; all volume channels
are also zero. Graphical runs use private Xvfb displays, background updates and
windowed preferences. Normal game exit and Steam/audio isolation are checked.
Installed game files and compilation references remain unchanged.

The initial migration map is in `state/migrations/20261101-layout.json`. Previous
mixed test/build scratch is in the seven-day `legacy-layout-20261101` session.
Pin it if it is needed longer. Old install backups are in `state/legacy-installs/`
and do not expire. Old installable packages are in `archive/user-outputs/`.

## Installation sync

`tools/rw sync` compares every active project against the selected RimSort
instance's local mods. It reports development changes since the latest build,
missing/unreadable build records, missing installs, different installed contents,
legacy packages, and duplicate package IDs. It compares installed bytes with the
built package on demand, without a stored hash inventory. A missing build is
reported as unbuilt.

After showing status, it numbers the out-of-date mods and asks which to build
and install. Press Enter (or enter `all`/`yes`) to update all of them, enter
comma-separated numbers such as `1,2,4` for a subset, or `no` to cancel. Numbers
refer to the displayed out-of-date list. Current packages are reused; missing,
stale, or invalid builds are rebuilt. Installation retains rollback backups.
No game is launched and the active mod list is unchanged.

```sh
tools/rw sync
tools/rw sync colony-groups --instance Default
tools/rw sync --no          # status only, no prompt or changes
tools/rw sync --all         # build/update all out-of-date mods without prompting
tools/rw sync --answer=1,2,4 # update a numbered subset without prompting
tools/rw sync --json        # status only, JSON output
tools/rw sync --check       # status only; exit 1 for drift
```

`--no`, `--all`, and `--answer` are mutually exclusive. `--json` and `--check`
cannot be combined with `--all` or `--answer`. End-of-input cancels the prompt.

Installation applies by default and retains rollback backups. `--dry-run` is the
explicit preview mode. Cleanup also applies by default, with `--dry-run` for a
preview. Activation remains separate. Rollback requires `--apply`.

## Workshop publication

The optional desktop backend uses the running Steam client's authenticated
session through RimWorld's installed `libsteam_api.so`. It requires online Steam
under the same Linux user with a RimWorld license, and no separate SteamCMD login.
Check the session without uploading:

```sh
tools/rw steam-probe
tools/rw steam-probe --item 3832323892  # also query Workshop dependencies, read-only
tools/rw publish kanban-refilled --backend desktop --dry-run
tools/rw publish kanban-refilled --backend desktop
```

Desktop publication is opt-in; SteamCMD remains the default. Both backends use
the same staged package, description, preview and release note. The desktop path
initializes Steamworks once in a child process, then polls asynchronous results
every 50 ms while waiting. It leaves no background worker after completion.
`--timeout SECONDS` limits the desktop upload wait (default 600). A timeout,
worker crash or missing final result is unconfirmed, not a successful upload;
check Workshop before retrying. There is no automatic retry or backend fallback.
Native logs remain in the upload session; publication receipts retain the final
Steamworks result when available. A successful read-only probe establishes session
and query access, but does not verify an upload.

`tools/rw publish PROJECT --dry-run` builds or reuses the current package and
prepares a SteamCMD upload without logging in. It prints the existing Workshop
item ID, version, change note, command and session directory. Inspect
`description.txt`, `change-note.txt` and `upload.vdf` there.

To publish, install Valve's SteamCMD and run:

```sh
tools/rw publish kanban-refilled --account STEAM_ACCOUNT
```

That command uploads the package, title, description, main preview and release
note. It requires an existing `About/PublishedFileId.txt`; it does not create
Workshop items. Visibility, tags and carousel images are left unchanged. First
login may need a password and Steam Guard; later automation can use SteamCMD's
remembered login. Passwords and Steam Guard codes are not arguments to `tools/rw`
or fields in upload files.

By default, the note comes from the matching version in CHANGELOG.md. Use
`--notes FILE` for another prepared note, `--steamcmd PATH` for an executable
outside PATH, and `--worktree PATH` for a different checkout. Upload staging and
logs are leased session files. Durable attempt receipts, including the item ID,
build identity, description, note and result, live in `state/publications/`.
A zero SteamCMD exit alone is not treated as successful publication.
