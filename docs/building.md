# Building mods with the shared tooling

This repository contains the shared build and test tooling for RimWorld 1.7.
Mod sources are independent Git repositories cloned into `projects/<key>/`.
They are not submodules. Clone only the mods you want to work on; the workspace
discovers each direct child containing `mod.toml` on every command. The folder
name must match the manifest's `key`. There is no registration command or central
mod list to edit.

## First checkout

The build tooling requires Linux, Git, uv, Python 3.11 or newer, the .NET 10 SDK,
a RimWorld 1.7 installation, and Harmony's 1.7 Workshop files (item 2009463077).
Game and dependency assemblies are read from your own installations and are not
included in these repositories. The Python orchestration currently uses Linux
file locking and process inspection; Windows and macOS are not supported.

Clone the [tooling repository](https://github.com/eiennohito/rimworld-mods)
wherever you want the workspace root to be. From that root, clone a mod repository
into the directory named by its `mod.toml` key. For example, clone
[Refilled](https://github.com/eiennohito/rimworld-kanbanstockpile-refilled)
into `projects/kanban-refilled/`:

```sh
git clone https://github.com/eiennohito/rimworld-mods.git
cd rimworld-mods
mkdir -p projects
git clone https://github.com/eiennohito/rimworld-kanbanstockpile-refilled.git projects/kanban-refilled
cp workspace.example.json workspace.json
```

Edit `workspace.json` to set `game` to the RimWorld installation directory
containing `Assembly-CSharp.dll`, and `workshop` to the Workshop app directory
`steamapps/workshop/content/294100`. Absolute paths, paths relative to the
workspace root, and `~` are accepted. The local config is ignored by Git.
Alternatively, provide existing `references/game` and `references/workshop`
directories or symlinks; these are the defaults when no config exists.

```sh
tools/rw setup
tools/rw list
tools/rw check
tools/rw build kanban-refilled
tools/rw latest kanban-refilled
```

`setup` checks the 1.7 version and creates reference links. It requires neither
RimSort nor a player profile. `check` runs infrastructure tests without launching
the game; it also checks the basic layout of discovered mod repositories.
The frozen uv lock selects the Python environment. `global.json` selects the
.NET SDK; the build uses the SDK's installed reference packs without NuGet feeds.

A build writes a clean, unpacked package into `outputs/mods/<key>/<build-id>/`.
It does not install, activate, archive or publish the mod. Compiler intermediates
and logs are leased scratch under `sessions/`, retained for seven days after use.
Outputs and installation backups persist. See [the lifecycle](lifecycle.md).

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
tooling or prose change. See [running isolated checks](running-rimworld.md) for
the isolation contract and additional graphical dependencies. A build alone
does not establish patch behavior.

## Optional local integrations

`workspace.json` can also set `rimsort`, `rimsort_data`, `player_data` and `ilspy`.
These are needed only for commands using those integrations. `ilspy` defaults
to `ilspycmd` on PATH; the other defaults are matching `references/` paths.
For example, installation uses `rimsort_data/settings.json`, and save probes use
`player_data/Config/ModsConfig.xml` unless an explicit config is supplied.

The repository's MIT license covers the original shared tooling and documentation.
Independent mods retain their own licenses and upstream notices. Game files,
downloaded mods, caches, player data, local config and publication receipts are
excluded from the tooling repository.
