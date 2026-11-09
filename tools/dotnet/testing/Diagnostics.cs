using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using HarmonyLib;
using RimWorld;
using UnityEngine;
using Verse;
using Verse.Steam;

namespace WorkspaceDiagnostics;

// The runner compiles the selected project's fixtures alongside this harness.
// No mod names or project-specific checks belong in this shared lifecycle.
[StaticConstructorOnStartup]
public static partial class Diagnostics
{
    internal static readonly List<object> Results = new();
    static partial void StartProject(ref bool pending);
    static partial void RunProjectChecks(List<object> tests);
    static Diagnostics() => LongEventHandler.ExecuteWhenFinished(() => {
        Prefs.RunInBackground = true;
        Application.runInBackground = true;
        bool pending = false;
        StartProject(ref pending);
        if (!pending) Export();
    });

    internal static void StartQuickTest()
    {
        LongEventHandler.QueueLongEvent(() => {
            Root_Play.SetupForQuickTestPlay();
            Find.GameInitData.mapSize = 150;
            PageUtility.InitGameStart();
        }, "GeneratingMap", true, GameAndMapInitExceptionHandlers.ErrorWhileGeneratingMap);
    }
    internal static void Finish() => Export();
    static object PatchRecord(Patch patch) => new {
        patch.owner, patch.priority, patch.index, patch.before, patch.after,
        method = patch.PatchMethod.ToString(), type = patch.PatchMethod.DeclaringType?.FullName,
        assembly = patch.PatchMethod.Module.Assembly.GetName().Name
    };
    static void Export()
    {
        try
        {
            var tests = new List<object>(Results);
            try { RunProjectChecks(tests); }
            catch (Exception ex) { tests.Add(new { error = ex.ToString() }); }
            var patches = Harmony.GetAllPatchedMethods().Select(method => {
                var info = Harmony.GetPatchInfo(method);
                return new {
                    targetType = method.DeclaringType?.FullName, targetMethod = method.Name,
                    signature = method.ToString(), assembly = method.Module.Assembly.GetName().Name,
                    prefixes = info.Prefixes.Select(PatchRecord).ToArray(),
                    postfixes = info.Postfixes.Select(PatchRecord).ToArray(),
                    transpilers = info.Transpilers.Select(PatchRecord).ToArray(),
                    finalizers = info.Finalizers.Select(PatchRecord).ToArray()
                };
            }).OrderBy(p => p.targetType).ThenBy(p => p.targetMethod).ToArray();
            var report = new {
                game = VersionControl.CurrentVersionStringWithRev, capturedUtc = DateTime.UtcNow,
                steam = new {
                    active = SteamManager.Active, initialized = SteamManager.Initialized,
                    nativeLibraryMapped = OperatingSystem.IsLinux() && File.ReadLines("/proc/self/maps")
                        .Any(line => line.Contains("libsteam_api.so") || line.Contains("steamclient.so"))
                },
                audio = new { backendActive = Waylith.Audio.AudioBackend.Current != null, masterVolume = Prefs.VolumeMaster },
                mods = LoadedModManager.RunningModsListForReading.Select(m => new {
                    packageId = m.PackageId, name = m.Name, root = m.RootDir,
                    assemblies = m.assemblies.loadedAssemblies.Select(a => a.GetName().Name).ToArray()
                }).ToArray(), tests, patches
            };
            string path = Path.Combine(GenFilePaths.SaveDataFolderPath, "report.json");
            File.WriteAllText(path, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            Log.Message("[WorkspaceDiagnostics] Wrote " + path);
            Application.Quit();
        }
        catch (Exception ex) { Log.Error("[WorkspaceDiagnostics] " + ex); }
    }
}
