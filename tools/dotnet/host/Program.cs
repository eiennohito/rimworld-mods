using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

if (args.Length == 4 && args[0] == "--no-audio")
{
    QuietAudio.Patch(args[1], args[2], args[3]);
    return;
}
if (args.Length != 3) throw new ArgumentException("Expected installed assembly, sandbox assembly, manifest.");
string source = Path.GetFullPath(args[0]), output = Path.GetFullPath(args[1]);
if (source == output || new FileInfo(output).LinkTarget != null)
    throw new InvalidOperationException("Output must be a separate regular sandbox file.");
byte[] original = File.ReadAllBytes(source), patched = (byte[])original.Clone();
using var pe = new PEReader(new MemoryStream(original));
var reader = pe.GetMetadataReader();
var replacements = new Dictionary<string, (byte[] signature, byte[] code)> {
    ["InitIfNeeded"] = (new byte[] { 0, 0, 1 }, new byte[] { 0x2a }),
    ["get_Active"] = (new byte[] { 0, 0, 2 }, new byte[] { 0x16, 0x2a })
};
var edits = new List<object>();
var validation = new List<(int rva, byte[] code)>();
foreach (var typeHandle in reader.TypeDefinitions)
{
    var type = reader.GetTypeDefinition(typeHandle);
    if (reader.GetString(type.Namespace) != "Verse.Steam" || reader.GetString(type.Name) != "SteamManager") continue;
    foreach (var methodHandle in type.GetMethods())
    {
        var method = reader.GetMethodDefinition(methodHandle);
        string name = reader.GetString(method.Name);
        if (!replacements.TryGetValue(name, out var replacement)) continue;
        if (!method.Attributes.HasFlag(MethodAttributes.Static)
            || !reader.GetBlobBytes(method.Signature).SequenceEqual(replacement.signature))
            throw new InvalidOperationException("Unexpected method signature: " + name);
        int rva = method.RelativeVirtualAddress;
        var section = pe.PEHeaders.SectionHeaders.Single(s => rva >= s.VirtualAddress
            && rva < s.VirtualAddress + s.SizeOfRawData);
        int offset = section.PointerToRawData + rva - section.VirtualAddress;
        int oldSize = pe.GetMethodBody(rva).GetILBytes().Length;
        if (replacement.code.Length > oldSize) throw new InvalidOperationException("Replacement is too large.");
        int headerSize;
        if ((patched[offset] & 3) == 2) {
            headerSize = 1;
            patched[offset] = (byte)((replacement.code.Length << 2) | 2);
        }
        else if ((patched[offset] & 3) == 3) {
            ushort flags = BinaryPrimitives.ReadUInt16LittleEndian(patched.AsSpan(offset, 2));
            headerSize = (flags >> 12) * 4;
            // The replacement has no exception regions. Unused old bytes stay untouched.
            BinaryPrimitives.WriteUInt16LittleEndian(patched.AsSpan(offset, 2), (ushort)(flags & ~8));
            BinaryPrimitives.WriteInt32LittleEndian(patched.AsSpan(offset + 4, 4), replacement.code.Length);
        }
        else throw new InvalidOperationException("Unsupported method body header: " + name);
        replacement.code.CopyTo(patched, offset + headerSize);
        validation.Add((rva, replacement.code));
        edits.Add(new { type = "Verse.Steam.SteamManager", method = name, rva,
            oldCodeSize = oldSize, newCodeSize = replacement.code.Length });
    }
}
if (edits.Count != replacements.Count) throw new InvalidOperationException("Expected Steam methods not found.");
using (var check = new PEReader(new MemoryStream(patched)))
    foreach (var edit in validation)
        if (!check.GetMethodBody(edit.rva).GetILBytes().SequenceEqual(edit.code))
            throw new InvalidOperationException("Patched IL verification failed.");
File.WriteAllBytes(output, patched);
File.WriteAllText(args[2], JsonSerializer.Serialize(new {
    source, output, edits
}, new JsonSerializerOptions { WriteIndented = true }) + "\n");
Console.WriteLine("Prepared sandbox assembly with Steam initialization disabled.");
