# RimWorld modding workspace

This is the single location for workspace agent guidance; do not add mod-local instruction files.
Read `README.md`, `tools/README.md`, `workspace.json` (or `workspace.example.json` before setup), `docs/rimworld-1.7.md` and the selected project's `README.md` before working.
Consult its development guide as needed.

## Source and implementation

- Investigate first and use an existing mod when it solves the issue; create a project only when code is needed.
- Active projects are independent Git repositories under `projects/<key>/` and support RimWorld 1.7 only.
- Prefer available upstream source and inspect current installed behavior when versions differ.
- A dependency declaring only 1.6 may work on 1.7; verify actual loading and behavior instead of rejecting its metadata.
- Preserve Git history, uncommitted work, licenses and source provenance; keep upstream contributions separate from workspace adaptations.
- Use worktrees and `--worktree PATH` for concurrent edits to the same project.
- Edit project sources; `references/`, linked assets, installed game files and Steam downloads are read-only.
- Reinspect relevant types after updates; do not collect assembly hashes or require historical fingerprints.
- Preserve supported mods' normal functionality, including inventory batching; bypassing an integration is an unresolved compatibility limitation.
- Use `tools/rw` for setup, inventory, decompilation, builds, tests and installation.
- Python orchestration belongs in the locked uv project in `tools/`; C# belongs in mods, fixtures and shared .NET helpers.
- Do not add per-mod build or installation scripts.

## Validation and budget

- Test the core functionality that defines the mod and ordinary player workflows.
- Choose the smallest check that answers a concrete question; inspection or compilation can suffice for small edits, but compilation does not prove patch behavior.
- Budget engine launches and simulated playtime before running checks; combining cases saves startup cost but not their simulation cost.
- Reuse fixtures and batch related assertions; do not expand test matrices for speculative corner cases.
- For most boundary operations, including settings changed during active work, accept sensible non-crashing outcomes and sometimes partial degradation unless a stricter outcome is an explicit contract.
- Crashes are unacceptable; stop testing once the behavior question is answered.
- Generated colonies and graphical runs need a question lighter checks cannot answer.
- Keep project fixtures in the project and shared harnesses independent of mod names.
- For text-only changes, inspect the edited text and relevant links or XML; do not build, launch the game or add tests solely to check prose.
- Report what checks establish and their material limits; helper checks do not establish a complete gameplay route.

## Game runs and artifacts

Read `docs/running-rimworld.md` before game runs and `docs/lifecycle.md` before creating scratch or cleaning files.
Use the shared isolated launcher with copied mods/saves, private XDG paths, Steam disabled, no-device audio and all volumes muted.
Graphical runs use private displays, windowed preferences and background updates; never take desktop input or focus.
Patch only sandbox copies; a timeout or forced termination is a failed run.

Builds belong in `outputs/mods/`, deliberately saved reports in `outputs/reports/`, leased scratch in `sessions/` and durable receipts/backups in `state/`.
Outputs are not automatically cleaned; scratch expires after seven days unless pinned.
Use shared cleanup commands and preserve live processes and pinned sessions.
Local development artifacts are authorized; installation, activation and publication each require a task requesting that action.
Installation applies by default (`--dry-run` previews), keeps backups and leaves the active mod list alone.
Builds do not create ZIPs or publish; requested Workshop publication follows `tools/README.md` and uses desktop Steam rather than the Steam-disabled test host.

## Documentation ownership

Before editing documentation, briefly identify the files, their readers and the purpose of the change.
Keep these boundaries instead of maintaining parallel technical explanations:

| Document | Owns |
| --- | --- |
| Project `README.md` | Why to use the mod, player-facing behavior, examples, compatibility, credits and a build link; some technical context is appropriate on GitHub |
| `About/Workshop.txt` | Player-focused Workshop presentation, examples, requirements and credits |
| `About/About.xml` | In-game functionality brief, controls and practical hints, plus game metadata |
| `DESIGN.md` | Concise architecture, code-navigation guidance, essential build/test commands and links to shared tooling procedures |
| `CHANGELOG.md` | Player-facing changes, with pending changes under `Unreleased` and published changes grouped by release |
| Workspace operating guides | Shared setup, build, test, publishing and lifecycle procedures |

README, Workshop and in-game copy may intentionally overlap because they serve different presentation contexts and change infrequently.
Developer documentation must have one owner per topic; link to that owner instead of repeating content that must be kept synchronized.
Do not add separate purpose, building, maintainer or usage documents when their content fits these boundaries; preserve retained upstream documentation and distinguish its environment from workspace adaptations.
Keep detailed algorithms and contracts beside their implementation, and test expectations in fixtures rather than duplicating them in prose.
Changelog entries describe changes players can notice, such as features, fixes, compatibility and meaningful limitations; omit internal refactors, routine tests and agent work logs.
Move relevant `Unreleased` entries into the versioned section when preparing a release; agents and contributors use Git history for implementation history.
Keep source provenance and license notices, but remove obsolete summaries and content that no longer helps its reader.
Routine work needs no report, validation diary or transcript; logs and temporary failures stay in scratch.
Prefer one sentence per Markdown source line; long sentences may break at natural punctuation within the sentence.
Do not reflow surrounding text when wording changes or manually wrap prose to a fixed column width; an established automatic formatter is also acceptable.
Use native game vocabulary and exact control labels in player copy, without task narration or internal implementation details.
Never invent measurements or present missing initial data as an error; qualify performance claims with initialization and recurring work costs.
