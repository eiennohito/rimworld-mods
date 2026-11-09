# RimWorld modding workspace

For coding agents. Read `README.md`, `tools/README.md`, `workspace.json`
(or `workspace.example.json` before local setup), `docs/rimworld-1.7.md`
and the selected project's `PURPOSE.md`. Read `docs/running-rimworld.md` before
game runs and `docs/lifecycle.md` before creating scratch or cleaning files.

- Investigate first; use an existing mod when it solves the issue. Create a
  project only when code is needed. Active mods are separate Git repositories
  under `projects/<key>/`, supporting RimWorld **1.7 only**.
- Preserve Git history, uncommitted work, upstream licenses and source provenance.
  Prefer upstream source; inspect installed behavior when versions differ.
  Use worktrees and `--worktree PATH` for concurrent edits to the same project.
- Edit project sources. `references/`, linked assets and Steam downloads are
  read-only. Work with current game/mod versions; inspect relevant types again
  when updates matter. Do not collect assembly hashes or require old fingerprints.
- Use `tools/rw` for setup, inventory, decompilation, builds, tests and installation.
  Python orchestration belongs in the locked uv project in `tools/`; C# belongs
  in mods, their fixtures and shared .NET helpers. No per-mod build/install scripts.
- Keep notes short and current: findings, non-obvious decisions and open issues.
  Replace superseded summaries. Routine work needs no report or validation diary;
  command output and temporary failures stay in session scratch.
- Follow `docs/documentation.md`. Before doc edits, briefly name the files,
  audience and purpose. Player copy uses native game vocabulary, without task
  narration or implementation details. Never invent measurements or show initial
  missing data as an error. Document initialization and recurring performance costs
  where they qualify claims. Maintain PURPOSE.md when intended behavior changes.
- Choose the smallest check that addresses a concrete risk. Inspection or a build
  can suffice for small edits; compilation alone does not establish patch behavior.
  Reuse tests and add fixtures for meaningful regressions. Batch engine assertions;
  generated colonies and graphical tests need a question lighter checks cannot answer.
  Project fixtures stay in the project; shared harnesses must not dispatch by mod name.
- Game runs must use the shared isolated launcher, copied mods/saves and private
  XDG paths. Keep Steam disabled, no-device audio and all volumes muted. Graphical
  runs use private displays, windowed preferences and background updates; never
  steal desktop input/focus. Patch only sandbox copies, leaving installed files
  unchanged. Timeout or forced termination is not a successful run.
- Unpacked builds go in `outputs/mods/`, deliberately saved reports in
  `outputs/reports/`; neither is automatically cleaned. Scratch goes in leased
  `sessions/` (seven days unless pinned); receipts/backups go in durable `state/`.
  Use shared cleanup commands, preserving live processes and pinned sessions.
- Local development artifacts are authorized. Installation, activation and
  publication each need a task requesting that action. Installation applies by
  default (`--dry-run` previews), keeps backups and leaves the active mod list alone.
  Builds never create ZIPs or publish to Steam.
