using HarmonyLib;
using UnityEngine;
using Verse;

// Compile-time coverage of the installed game, Unity compatibility API, and Harmony.
public sealed class WorkspaceBuildProbe : Mod
{
    public WorkspaceBuildProbe(ModContentPack content) : base(content)
    {
        Log.Message("Workspace build probe loaded from " + content.RootDir
            + "; Mods=" + GenFilePaths.ModsFolderPath
            + "; Harmony=" + typeof(Harmony).Assembly.GetName().Version);
    }
    public static Vector2 Size => new Vector2(320, 240);
    public static Harmony CreatePatcher() => new Harmony("local.workspace.buildprobe");
}
