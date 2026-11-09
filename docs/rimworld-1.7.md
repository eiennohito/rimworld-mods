# RimWorld 1.6 to 1.7 notes

Checked 2026-10-31. Refresh these sources before relying on changing beta details.

For launch commands, screenshots and isolated test profiles, see
[Running RimWorld tests and screenshots](running-rimworld.md).

## Ludeon's guidance

1.7 runs Waylith/.NET 10 with a Unity compatibility layer. Existing 1.6 binaries
are intended to work in most cases without recompilation. Prepatcher and asset
loading modifications are exceptions requiring special attention. Rebuilds should
target `net10.0` and reference `Assembly-CSharp.dll`, `UnityStubs.dll`, `Waylith.dll`,
and optionally the `RimWorld.dll` host. Keeping existing Unity API calls is supported.
Legacy dependency assemblies can prevent recompilation even if they run unchanged.

The primer documents `-Headless`, `-NoWindow`, `-mod=`, shader watching and asset
pack baking. Vulkan-compatible Linux asset bundles are needed for legacy shaders;
new shaders use GLSL plus shader/material definitions. The frame profiler can
instrument selected methods and allocations. Consult the full primer for details.

Source: [Ludeon Modder Primer for 1.7](https://docs.google.com/document/d/e/2PACX-1vSykw5_DYaaw42nEznI9zmBZVT_Vgg2bxYq_v2XWvAsHC3QSKFuDK2OyiQ5WC9jvVRUcrjpFt7xLLF5/pub).

Ludeon announced the unstable branch on October 12, 2026, and recommends testing
before adding 1.7 to supported versions. A version warning alone does not establish
that a mod is broken.
Source: [Ludeon announcement](https://ludeon.com/blog/2026/10/announcing-the-waylith-engine-and-update-1-7/).

## Harmony

The upstream RimWorld Harmony project specifies Harmony 3 for 1.7/.NET 10 and
Harmony 2.4.3 for 1.6/.NET Framework 4.7.2. Use the matching version folder from the
installed dependency rather than bundling a second Harmony copy.
Source: [HarmonyRimWorld](https://github.com/pardeike/HarmonyRimWorld).

## Current reference build

On 2026-10-31, Steam updated this installation to **1.7.4995 rev309**.
An inventory was taken; the then-current decompile was in
`artifacts/decompiled/game-1.7.4995/`. The sandbox host was refreshed with
`tools/rw setup`. The older decompile and the observations below belong to 4990.

## Findings from the original 1.7.4990 reference build

- `Version.txt`: **1.7.4990 rev1069**. Steam manifest: build **26222807**, branch
  **unstable**. Assemblies live directly under the game root.
- Runtime configuration: `net10.0`, bundled runtime `10.0.13-waylithclr.dev`.
  The game uses a modified runtime, not the system Mono installation.
- Runtime configuration redirects `UnityEngine*` to `UnityStubs` and enables
  compatibility switches. Thus successful execution of an old DLL and successful
  recompilation against the new reference set are distinct checks.
- Installed `Verse.ModsConfig.ApplyCommandLineModList` rejects Workshop-source mods
  for `-mod=`. Stage local copies. Core and installed DLC are added automatically;
  the mod list is sorted and ModsConfig.xml is bypassed.
- Installed `RimWorldWaylith.Bootstrap` resolves early logs from `XDG_CONFIG_HOME`
  on Linux. `-savedatafolder` redirects game data but not those early logs.
  The workspace launcher sets both.
- `Verse.GenFilePaths.GetOrCreateModsFolder` locates Mods relative to the host
  executable. The sandbox contains a real copy of that executable with local Mods.
- The example declares only 1.6 and has a `LoadFolders.xml` 1.6 entry. Test actual
  assembly loading and patch application before changing version metadata or
  adding 1.7 load folders. Do not treat a metadata edit as a functional fix.

Local evidence: `artifacts/game-reference.json`,
`artifacts/decompiled/game-types/Verse.ModsConfig.cs`,
`artifacts/decompiled/game-types/Verse.GenFilePaths.cs`, and
`artifacts/decompiled/host-types/RimWorldWaylith.Bootstrap.cs`.

For any future patch: reproduce with the original DLL first, find the first error,
inspect the exact installed method signature/IL, fix the smallest relevant code,
compile, then test patch application and behavior with the required dependency
set. Preserve a working 1.6 branch if dual-version support matters.


## Workspace restructuring note (2026-11-01)

Active projects now live in `projects/` and support 1.7 only. Game version
and Workshop inventory are cached under `.cache/inventory/`; built installable
packages are under `outputs/mods/`. Old decompilations and reports mentioned above
were moved into the seven-day `legacy-layout-20261101` session. Those paths are
historical evidence, not current build references. Pin that session if needed
longer, or decompile the live reference into a new session with `tools/rw decompile`.

Test hosts also copy Waylith.dll and force its existing no-device audio mode.
Original compilation references and installed game files are never patched.
See `docs/running-rimworld.md` and `docs/lifecycle.md` for current commands.
