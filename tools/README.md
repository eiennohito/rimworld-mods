# Building mods with the shared tooling

This repository contains the shared build and test tooling for RimWorld 1.7.
Run the commands in this guide from the workspace root, above `tools/`.
Mod sources are independent Git repositories cloned into `projects/<key>/`.
They are not submodules. Clone only the mods you want to work on; the workspace
discovers each direct child containing `mod.toml` on every command. The folder
name must match the manifest's `key`. There is no registration command or central
mod list to edit.

## Working with a coding agent

The workspace is designed primarily for AI coding agents. Codex and Claude Code
both work well with it; the commands below are also usable directly.

Use Codex or Claude Code from the workspace root and describe what you want
investigated or changed—for example, “Find why pawns keep refilling this shelf.”

The important feedback loop is testing behavior in the game. An agent can write
a focused scenario, run it in a headless RimWorld simulation, inspect the result
and revise the mod. For example, a hauling scenario could send two pawns toward
the same limited stockpile and check whether their deliveries overfill it.
Keeping the scenario as a regression test makes later changes easier to check.

The Linux launcher uses a separate host, copied mods and private game data, with
Steam disabled and audio muted. Scenarios can use real game objects and advance
the simulation, so checks can cover interactions that compilation alone cannot
establish. Coverage depends on what each scenario actually exercises; a direct
quantity check does not establish a complete pawn hauling route. Headless runs
still pay the game startup cost, so use smaller checks where sufficient and
batch related assertions into one run. See [running isolated checks](../docs/running-rimworld.md)
for fixtures, save probes and results.

## Prerequisites

| Requirement | Used for |
| --- | --- |
| Linux | The launcher, file locking and process inspection; Windows and macOS are not supported yet |
| Git | Independent workspace and mod repositories, source revision records |
| uv | Running the locked Python environment through `tools/rw` |
| Python | The wrapper selects Python 3.12 via `.python-version`; the code requires 3.11 or newer |
| .NET 10 SDK | Compiling mods and test fixtures; selected by the root `global.json` |
| RimWorld 1.7, installed locally | Game assemblies for compilation and the engine for simulation tests |
| Harmony's 1.7 files | Refilled and the shared mod reference set; Workshop item 2009463077 |

Game and dependency assemblies are read from your own installations and are not
included in these repositories. Download any other dependencies required by the
mod you are working on.

| Optional tool or integration | Needed when |
| --- | --- |
| Codex or Claude Code | Working with a coding agent |
| RimSort with a configured instance | Installing and syncing builds into that instance's local mod folder |
| ILSpy command-line tool (`ilspycmd`) | Inspecting installed game and mod code with `tools/rw decompile` |
| Desktop Steam, online with a RimWorld license | Publishing Workshop updates using the desktop session |
| Xvfb and Mesa software Vulkan | Running graphical scenarios or capturing screenshots; see [display setup](../docs/running-rimworld.md#isolation) |

RimSort is not needed to build or run isolated tests. For installation and sync,
the tooling reads its existing `settings.json`; it does not create a RimSort
instance or change the active mod list.

## Initial configuration

Clone the workspace and the mod you want to work on. For Refilled:

```sh
git clone https://github.com/eiennohito/rimworld-mods.git
cd rimworld-mods
mkdir -p projects
git clone https://github.com/eiennohito/rimworld-kanbanstockpile-refilled.git projects/kanban-refilled
```

An agent can help with setup, especially when Steam libraries or RimSort data
are in different locations. Ask it:

> Set up this workspace for RimWorld 1.7 on this machine. Find my game, Workshop
> files and RimSort instance, check the prerequisites, and configure the local paths.

For direct configuration, supply your installation paths:

```sh
tools/rw setup --game "/path/to/steamapps/common/RimWorld" \
  --workshop "/path/to/steamapps/workshop/content/294100"
```

This writes the Git-ignored `workspace.json`, checks the game version and creates
reference links. `--game` points to the directory containing `Assembly-CSharp.dll`.
Paths can be absolute, relative to the workspace root, or start with `~`.
Existing configuration fields are retained, and conflicting reference links are
reported without being replaced. Rerun `tools/rw setup` to check existing paths.

Add `--rimsort-data "/path/to/RimSort/data"` to configure the directory containing
RimSort's `settings.json`. Other optional flags are `--rimsort`, `--player-data`
and `--ilspy`; see `tools/rw setup --help`. You can also edit `workspace.json`
directly using `workspace.example.json` as a starting point. Existing
`references/game` and `references/workshop` directories or symlinks work as defaults.

Once configured:

```sh
tools/rw setup
tools/rw list
tools/rw check
tools/rw build kanban-refilled
tools/rw latest kanban-refilled
```

`check` runs infrastructure tests without launching the game; it also checks
the basic layout of discovered mod repositories.
The frozen uv lock selects the Python environment. `global.json` selects the
.NET SDK; the build uses the SDK's installed reference packs without NuGet feeds.

A build writes a clean, unpacked package into `outputs/mods/<key>/<build-id>/`.
It does not install, activate, archive or publish the mod. Compiler intermediates
and logs are leased scratch under `sessions/`, retained for seven days after use.
Outputs and installation backups persist. See [the lifecycle](../docs/lifecycle.md).

## Editing and checking a mod

Each mod owns its source, license, content, manifest and fixtures. Read its
`PURPOSE.md` and `BUILDING.md`. To use another checkout inside the workspace:

```sh
tools/rw build kanban-refilled --worktree worktrees/refilled-change
```

The shared build command supplies `WorkspaceRoot`, `RimWorldDir` and `HarmonyDir`
to MSBuild, so worktrees do not need their own scripts. You can clone a mod,
read it, change it and manage its Git history independently of this repository.
The shared tooling is needed for the documented packaging and game-test commands.

Game-backed tests use an isolated host and copied mods. Headless fixtures still
start RimWorld; run them for a behavior question, not to validate a source-only
tooling or prose change. See [running isolated checks](../docs/running-rimworld.md) for
the isolation contract and additional graphical dependencies. A build alone
does not establish patch behavior.

## Optional local integrations

`workspace.json` can also set `rimsort`, `rimsort_data`, `player_data` and `ilspy`.
These are needed only for commands using those integrations. `ilspy` defaults
to `ilspycmd` on PATH; the other defaults are matching `references/` paths.
For example, installation uses `rimsort_data/settings.json`, and save probes use
`player_data/Config/ModsConfig.xml` unless an explicit config is supplied.

The repository's [MIT license](../LICENSE) covers the original shared tooling and documentation.
Independent mods retain their own licenses and upstream notices. Game files,
downloaded mods, caches, player data, local config and publication receipts are
excluded from the tooling repository.

## Workshop updates

Publishing defaults to the running desktop Steam session. Steam must be online
under the same Linux user with a RimWorld license; no separate login is needed.
The command updates the existing item named by `About/PublishedFileId.txt` with
the built package, title, description, main preview and release note.

```sh
tools/rw steam-probe --item 3832323892
tools/rw publish kanban-refilled --dry-run
tools/rw publish kanban-refilled
```

Review the staged description and change note from the dry run before publishing.
By default, the note comes from the matching version in `CHANGELOG.md`; use
`--notes FILE` for a metadata-only update. Tags, visibility and carousel images
are retained. Receipts live in `state/publications/`; logs use leased sessions.
A missing final result is unconfirmed: inspect the live Workshop item before
retrying, because Steam may have committed the update.

SteamCMD is available only with `--backend steamcmd`. It requires `--account`
and may log out the desktop client. Supplying SteamCMD options does not switch
the backend automatically.
