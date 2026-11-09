using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Linq;
using Microsoft.Diagnostics.Tracing;
using Microsoft.Diagnostics.Tracing.Etlx;

var records = new List<object>();
var counts = new Dictionary<string, int>();
using var source = new EventPipeEventSource(args[0]);
source.Clr.All += e => {
    string name = e.EventName;
    counts.TryGetValue(name, out int count);
    counts[name] = count + 1;
    if (!name.Contains("GC") && !name.Contains("Contention")) return;
    var payload = new Dictionary<string, string>();
    for (int i = 0; i < e.PayloadNames.Length; i++)
        payload[e.PayloadNames[i]] = e.PayloadValue(i)?.ToString();
    records.Add(new { name, ms = e.TimeStampRelativeMSec, thread = e.ThreadID, payload });
};
source.Process();
File.WriteAllText(args[1], JsonSerializer.Serialize(new { counts, events = records }, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"Decoded {records.Count} runtime events.");

string etlx = Path.ChangeExtension(args[1], ".etlx");
TraceLog.CreateFromEventPipeDataFile(args[0], etlx);
using var log = new TraceLog(etlx);
var addresses = new Dictionary<string, int>();
foreach (var e in log.Events)
{
    if (e.ProviderName != "Microsoft-DotNETCore-SampleProfiler") continue;
    for (var stack = e.CallStack(); stack != null; stack = stack.Caller)
    {
        var address = stack.CodeAddress;
        string name = address.FullMethodName;
        if (!name.Contains("GetValueUnfinalized_Patch") && !name.Contains("IsSealedWithCache") && !name.Contains("PollGC") && !name.Contains("Monitor.Enter")) continue;
        string key = name + " @ 0x" + address.Address.ToString("x");
        addresses.TryGetValue(key, out int count);
        addresses[key] = count + 1;
    }
}
File.WriteAllText(Path.ChangeExtension(args[1], ".addresses.json"), JsonSerializer.Serialize(
    addresses.OrderByDescending(kv => kv.Value).Select(kv => new { location = kv.Key, samples = kv.Value }),
    new JsonSerializerOptions { WriteIndented = true }));
