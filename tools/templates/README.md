# Project template

A project is a Git repository under `projects/<key>/`.
A fork preserves upstream history or records its source snapshot; a patch mod has its own package ID and declares the original as a dependency.
An issue resolved by an existing mod needs a brief finding when worth saving, not an empty project.

Start with `mod.toml` and `README.md`, explaining why to use the mod, its intended player behavior, dependencies and meaningful limits.
Follow the workspace [documentation ownership policy](../../AGENTS.md#documentation-ownership).
Use `About/Workshop.txt` for Workshop presentation and `About/About.xml` for the in-game reference.

Put C# code and the project file under `Source/`, with standard RimWorld metadata and assets at the repository root.
A 1.7 project can import the common references:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <WorkspaceRoot Condition="'$(WorkspaceRoot)' == ''">$(MSBuildThisFileDirectory)../../..</WorkspaceRoot>
    <AssemblyName>YourMod</AssemblyName>
  </PropertyGroup>
  <Import Project="$(WorkspaceRoot)/tools/dotnet/RimWorld17.props" />
</Project>
```

`tools/rw build` supplies workspace/reference properties, including when building from a Git worktree.

Game-backed checks live in `tests/runtime/`.
They can implement the generic harness's partial `RunProjectChecks(List<object>)` and `StartProject(ref bool)` hooks in the `WorkspaceDiagnostics.Diagnostics` class.
Only this project's fixtures are compiled into its test helper and they are excluded from the installed mod package.
See [running isolated checks](../../docs/running-rimworld.md) for harness usage and the workspace [validation policy](../../AGENTS.md#validation-and-budget) for choosing and budgeting checks.
