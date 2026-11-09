using System;
using System.Buffers.Binary;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;

internal static class QuietAudio
{
    public static void Patch(string source, string output, string manifest)
    {
        if (Path.GetFullPath(source) == Path.GetFullPath(output) || new FileInfo(output).LinkTarget != null)
            throw new InvalidOperationException("A separate regular sandbox engine copy is required.");
        byte[] original = File.ReadAllBytes(source), changed = (byte[])original.Clone();
        using var pe = new PEReader(new MemoryStream(original));
        var reader = pe.GetMetadataReader();
        var codes = typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static).Where(f => f.FieldType == typeof(OpCode))
            .Select(f => (OpCode)f.GetValue(null)!).ToDictionary(o => unchecked((ushort)o.Value));
        int edits = 0;
        foreach (var typeHandle in reader.TypeDefinitions)
        {
            var type = reader.GetTypeDefinition(typeHandle);
            if (reader.GetString(type.Namespace) != "Waylith.Audio.MiniAudio" || reader.GetString(type.Name) != "MiniAudioBackend") continue;
            foreach (var methodHandle in type.GetMethods())
            {
                var method = reader.GetMethodDefinition(methodHandle);
                if (reader.GetString(method.Name) != "Initialize") continue;
                if (!reader.GetBlobBytes(method.Signature).SequenceEqual(new byte[] { 0x20, 1, 1, 2 }))
                    throw new InvalidOperationException("Unexpected MiniAudioBackend.Initialize(bool) signature.");
                if (!method.GetParameters().Any(h => { var p = reader.GetParameter(h); return p.SequenceNumber == 1 && reader.GetString(p.Name) == "noAudio"; }))
                    throw new InvalidOperationException("Expected noAudio parameter was not found.");
                int rva = method.RelativeVirtualAddress;
                byte[] il = pe.GetMethodBody(rva).GetILBytes()!;
                var section = pe.PEHeaders.SectionHeaders.Single(s => rva >= s.VirtualAddress && rva < s.VirtualAddress + s.SizeOfRawData);
                int body = section.PointerToRawData + rva - section.VirtualAddress;
                int header = (original[body] & 3) == 2 ? 1 : (BinaryPrimitives.ReadUInt16LittleEndian(original.AsSpan(body, 2)) >> 12) * 4;
                for (int offset = 0; offset < il.Length;)
                {
                    int instruction = offset;
                    ushort code = il[offset++];
                    if (code == 0xfe) code = (ushort)(0xfe00 | il[offset++]);
                    var op = codes[code];
                    int length = op.OperandType switch {
                        OperandType.InlineNone => 0,
                        OperandType.ShortInlineBrTarget or OperandType.ShortInlineI or OperandType.ShortInlineVar => 1,
                        OperandType.InlineVar => 2,
                        OperandType.InlineI8 or OperandType.InlineR => 8,
                        OperandType.InlineSwitch => 4 + 4 * BinaryPrimitives.ReadInt32LittleEndian(il.AsSpan(offset, 4)),
                        _ => 4
                    };
                    if (op == OpCodes.Ldarg_1)
                    {
                        // Keep the backend/groups available to RimWorld, but use
                        // the same no-device initialization as a headless host.
                        changed[body + header + instruction] = 0x17; // ldc.i4.1
                        edits++;
                    }
                    offset += length;
                }
            }
        }
        if (edits != 1) throw new InvalidOperationException("Expected exactly one noAudio argument read.");
        using (var verification = new PEReader(new MemoryStream(changed)))
            if (verification.GetMetadataReader().TypeDefinitions.Count != reader.TypeDefinitions.Count)
                throw new InvalidOperationException("Patched engine verification failed.");
        File.WriteAllBytes(output, changed);
        File.WriteAllText(manifest, JsonSerializer.Serialize(new {
            source, output, edits, noAudio = true
        }, new JsonSerializerOptions { WriteIndented = true }) + "\n");
        Console.WriteLine("Prepared sandbox engine with no-device audio initialization.");
    }
}
