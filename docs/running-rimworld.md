# Running isolated RimWorld 1.7 checks

Choose a check for a concrete question. Inspection or compilation may suffice;
use existing focused fixtures before adding tests. `tools/rw check` covers shared
Python tooling without starting the game. Headless runs still start the engine,
so batch assertions. Generated colonies and graphical runs are for questions
lighter checks cannot answer, not routine finish steps.

```sh
tools/rw build PROJECT
tools/rw test PROJECT --suite runtime
tools/rw test PROJECT --suite runtime --with PACKAGE_ID
```

Use `--with-mod PATH` to test against a local mod directory inside the workspace,
including a source-built dependency in a leased session. It must contain
`About/About.xml` and its runtime files. The launcher copies it into the isolated
host; it does not install or activate it. Its package ID overrides an installed
copy for that test only, and its declared dependencies are included.

Suites are declared in each project's `mod.toml`; fixtures live in its `tests/`.
They use the generic shared reporting harness, without per-mod dispatch in shared
code. Use `--worktree PATH` for independent edits of the same project.
Rendering is needed for drawing/input/layout questions; passing headless checks
do not need repeating graphically. Screenshots can establish layout without
establishing a complete gameplay route.

## Isolation

Always use the shared launcher. Each run gets a copied host, mod set, saves,
preferences and private XDG paths under its leased session. Do not run an installed
or mirrored executable directly. Source game files, Workshop downloads and live
saves remain read-only; newer builds cannot mutate an existing run's copied mods.

Host files, mod snapshots and probe saves use reflinks when supported, sharing
disk blocks until either copy changes. Unsupported filesystems use ordinary
copies. Hardlinks are avoided because in-place writes would change both copies.
Each run still generates its own texture cache; reflinks do not reduce that cost
or retroactively deduplicate existing sessions.

Cached sandbox copies disable SteamManager initialization and force Waylith's
MiniAudio backend into its supported no-device mode. The helpers check method
signatures and record edits in `steamless-host.json` and `quiet-audio.json`.
Keep the audio backend for the game's mixer groups and mute all five channels.
Compilation uses current installed references.

Graphical runs use private Xvfb displays (`-displayfd`, `-extension GLX`), windowed
1280×800 preferences, background updates and Mesa software Vulkan. The launcher
removes desktop activation variables and refuses desktop fallback. Never steal
input/focus or connect to desktop audio. Private sockets may need sandbox approval.
Required renderer/display files are:

```text
.cache/virtual-display/usr/bin/Xvfb
.cache/software-vulkan/usr/lib/libvulkan_lvp.so
.cache/software-vulkan/usr/share/vulkan/icd.d/lvp_icd.json
```

## Results and failures

`report.json` contains loaded mods, Harmony owners and fixture checks;
`result.json` records the outcome. Success requires passing checks, requested mods
loaded, normal zero exit, Steam inactive/uninitialized without mapped native Steam
libraries, and muted no-device audio. Timeouts, missing reports and forced stops
are failures. Inspect `run.log` and isolated `xdg/config/` logs when needed.
`Wayland: Platform not initialized` alone is not fatal on the software renderer.

Summarize the result and material limits briefly. Session artifacts expire after
seven days; pin or save reports only when their evidence is worth retaining.
See [the lifecycle](lifecycle.md) for commands and cleanup.

## Inspecting assemblies and saves

```sh
tools/rw --session inspect-hauling decompile references/game/Assembly-CSharp.dll --type Verse.StoreUtility
tools/rw --session save-investigation probe investigations/ISSUE/tests/SaveProbe.csproj --save references/player_data/Saves/NAME.rws
```

Decompilations describe the inspected version. Reinspect relevant current types
when updates affect the question; no assembly hash inventory is needed.

A save probe fixture uses `WorkspaceDiagnostics` partial hooks, builds an assembly
named `SaveProbe` and includes `tools/dotnet/testing/Diagnostics.cs`. Before a mod
exists it belongs in the investigation; regression fixtures belong in the project.

Probes copy the save, active mods and settings, preserving configured mod order.
Profiler preferences are excluded. The fixture loads the copied save and calls
`Finish()` after its checks. Add `--package PATH` to replace an already active mod
with a built package in the isolated host; repeat for multiple replacements.
Current game/mod dependencies are used without rejecting older build records.

## Live stalls

```sh
tools/rw --session live-stall trace --pid PID --seconds 30
```

Use a short EventPipe sample when the problem disappears in fresh processes.
The tool requires `.cache/tools/dotnet-trace/dotnet-trace` and targets a running
RimWorld process without stopping it or modifying game files. Access may require
leaving the sandbox PID namespace. A restarted process needs its new PID.
Failed attachment produces no sampling result. Collection has overhead; sampled
stacks are not exact per-call durations.
