# Files and cleanup lifecycle

There are two separate classes of generated files. **Outputs are for the user;
sessions are disposable working data.** Shared commands never place raw compiler
output or test hosts in `outputs/`.

## Persistent output and state

- `outputs/mods/<project>/<build-id>/` is an unpacked, built RimWorld mod.
  It contains game-loadable content and `build.json`, not compiler caches, game
  references, test fixtures or ZIP files. Builds never merge into an old package.
- `outputs/reports/<name>/` contains deliberately saved reports and captures.
  Reports are promoted explicitly, not saved there after every experimental run.
- `state/installs/<instance>/<project>/<installation-id>/` contains installation
  receipts and rollback backups. These never expire with test sessions.
- Projects, authored investigations and historical source archives are durable.

There is **no automatic deletion** of any of these. Removing old user outputs or
installation backups requires a separate, explicit cleanup decision.

## Session scratch: seven days

Each scratch-producing `tools/rw` command gets a session, or reuses `--session ID`.
It records ownership and an expiry in `sessions/ID/session.json`.

```text
sessions/ID/
  session.json                 Ownership, status, pin and expiry
  build/                       Raw compiler output, logs and intermediate files
  runs/RUN-ID/                 One complete execution
    game/                      Private host and copied mod snapshot
    data/                      Isolated saves and preferences
    xdg/                       Isolated early logs/runtime/configuration
    harness-build/             This run's compiled project-specific fixtures
    screenshots/               Captures copied out of the profile
    inputs.json                Selected packages, fixture/suite and game version
    report.json                Game-side results
    result.json                Runner outcome, including failures
    run.log                    Host output
  decompiled/                  Inspection source recovered for this session
```

The lifecycle is:

1. A command acquires its named session lease and records its process identity.
2. Child game and virtual-display processes are registered. Their PID and process
   start time prevent an unrelated reused PID from being mistaken for the owner.
3. Completion marks the session finished and sets expiry to **seven days later**.
   Reusing the session refreshes that deadline. Running packages are independent
   snapshots, not links into mutable build output.
4. A live process or a pin prevents collection. An interrupted session whose
   recorded processes have all exited is marked abandoned on discovery and gets
   a fresh seven-day retention period.
5. Expired, unpinned sessions with no live processes are collected at the start of
   ordinary `tools/rw` commands. There is **no background timer or service**.
   Without another command, expired files remain until explicit cleanup.

```sh
tools/rw clean                       # collect eligible expired sessions
tools/rw clean --dry-run             # preview eligible expired sessions
tools/rw clean --all                 # collect all inactive, unpinned sessions
tools/rw clean --all --dry-run       # preview collection before seven-day expiry
tools/rw pin SESSION-ID              # retain a session indefinitely
tools/rw pin SESSION-ID --remove     # allow its recorded expiry to apply again
tools/rw save-report SESSION-ID --name reviewed-result
```

`clean`, `pin` and `save-report` do not first run automatic collection, so a preview
cannot delete files and an expired session can still be pinned. Saved reports
include results, inputs, logs, host manifests and screenshots, not entire game
hosts or saves. A session must finish before its reports can be saved.

`clean --all` bypasses session retention only when explicitly requested. Pins and
live processes still prevent removal; persistent outputs and state are untouched.

## Cache policy

`.cache/` holds reusable SDK/NuGet/uv packages, renderer/display binaries, prepared
hosts and helper compiler caches. It never holds user-facing deliverables.

```sh
tools/rw clean cache                 # clear rebuildable caches while unused
tools/rw clean cache --dry-run       # preview rebuildable cache directories
```

Cache cleanup takes an exclusive lease; build/test commands hold shared leases.
It can wait for active commands to finish. It clears helper outputs, host copies,
temporary files, old compiler caches and cached inventories. Downloaded SDK,
NuGet, uv, renderer and display packages are retained for offline reuse; removing
those is a deliberate toolchain-maintenance operation, not session cleanup.

## Initial migration

The old `artifacts/`, `runs/` and sandbox were previously mixed and had no expiry.
Remaining session-only data was moved into `sessions/legacy-layout-20261101/`
with a seven-day deadline. The migration map identifies old and new prefixes.
Old installation backups were extracted into durable `state/legacy-installs/`.
Old installable packages/releases were retained under `archive/user-outputs/`.
No legacy user package or rollback backup is automatically pruned.
