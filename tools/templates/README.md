# Project template

A project is a Git repository under `projects/<key>/`. A fork preserves upstream
history or records its source snapshot; a patch mod has its own package ID and
declares the original as a dependency. An issue resolved by an existing mod needs
a brief finding when worth saving, not an empty project.

Start with `mod.toml` and `PURPOSE.md`. The purpose document explains the intended
player behavior, what happens in a concrete example, dependencies, and meaningful
limits. Keep detailed implementation notes in `docs/`.

Put C# code and the project file under `Source/`, with standard RimWorld metadata
and assets at the repository root. A 1.7 project can import the common references:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <WorkspaceRoot Condition="'$(WorkspaceRoot)' == ''">$(MSBuildThisFileDirectory)../../..</WorkspaceRoot>
    <AssemblyName>YourMod</AssemblyName>
  </PropertyGroup>
  <Import Project="$(WorkspaceRoot)/tools/dotnet/RimWorld17.props" />
</Project>
```

`tools/rw build` supplies the workspace/reference properties, including when
building from a Git worktree. Do not write a new build/install script.

Game-backed checks live in `tests/runtime/`. They can implement the generic
harness's partial `RunProjectChecks(List<object>)` and `StartProject(ref bool)`
hooks in the `WorkspaceDiagnostics.Diagnostics` class. Only this project's
fixtures are compiled into its test helper. See the three existing projects for
examples. Fixtures are excluded from the installed mod package.

## Test cost

Prefer lightweight logic checks and targeted headless fixtures for basic behavior.
Choose checks for a concrete risk; routine edits need no new fixture or test diary.
The headless runtime harness still starts the engine, so batch related assertions
into one invocation. Generated-colony and rendered UI scenarios are last resorts
for a named question those checks cannot answer; do not require them after every
edit or duplicate passing headless checks through the UI.
