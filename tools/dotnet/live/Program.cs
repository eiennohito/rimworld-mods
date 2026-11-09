using System;
using System.Linq;
using System.Text.Json;
using Microsoft.Diagnostics.Runtime;

using var target = DataTarget.AttachToProcess(int.Parse(args[0]), suspend: false);
// Waylith's matching runtime/DAC binaries advertise zero version metadata.
// The launcher verifies that both come from the running game's directory.
using var runtime = target.ClrVersions[0].CreateRuntime(args[1], ignoreMismatch: true);
var module = runtime.EnumerateModules().First(m => m.Name != null && m.Name.EndsWith("Assembly-CSharp.dll"));
var type = module.GetTypeByName("Verse.ThingWithComps") ?? throw new Exception("ThingWithComps type unavailable.");
var field = type.GetStaticFieldByName("EmptyCompsList") ?? throw new Exception("Shared empty component list unavailable.");
var list = field.ReadObject(runtime.AppDomains[0]);
int count = list.ReadField<int>("_size");
var items = list.ReadObjectField("_items").AsArray();
var entries = Enumerable.Range(0, Math.Min(count, 30)).Select(i => new {
    index = i, type = items.GetObjectValue(i).Type?.Name, address = items.GetObjectValue(i).Address.ToString("x")
}).ToArray();
Console.WriteLine(JsonSerializer.Serialize(new { sharedEmptyComponentCount = count, capacity = items.Length,
    listAddress = list.Address.ToString("x"), entries }, new JsonSerializerOptions { WriteIndented = true }));
