using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text;
using System.Text.Json;

// Reads PE metadata only. Mod assemblies are never loaded or executed here.
string[] targetTypes = { "StoreUtility", "HaulAIUtility", "StorageSettings", "Toils_Haul",
    "WorkGiver_HaulGeneral", "JobDriver_HaulToCell", "GridsUtility" };
string[] targetMethods = { "NoStorageBlockersIn", "HaulToStorageJob", "HaulToCellStorageJob",
    "TryFindBestBetterStorageFor", "TryFindBestBetterStoreCellFor", "IsGoodStoreCell",
    "GetItemStackSpaceLeftFor", "TryAbsorbStack", "CanStackWith", "TryPlaceThing", "CapacityAt" };
var reports = new List<object>();
foreach (var path in args)
{
    try
    {
        using var stream = File.OpenRead(path);
        using var pe = new PEReader(stream);
        if (!pe.HasMetadata) continue;
        var reader = pe.GetMetadataReader();
        string TypeName(EntityHandle handle) {
            if (handle.Kind == HandleKind.TypeReference) {
                var type = reader.GetTypeReference((TypeReferenceHandle)handle);
                if (type.ResolutionScope.Kind == HandleKind.TypeReference)
                    return TypeName(type.ResolutionScope) + "+" + reader.GetString(type.Name);
                string ns = reader.GetString(type.Namespace);
                return (ns.Length > 0 ? ns + "." : "") + reader.GetString(type.Name);
            }
            if (handle.Kind == HandleKind.TypeDefinition) {
                var type = reader.GetTypeDefinition((TypeDefinitionHandle)handle);
                if (!type.GetDeclaringType().IsNil)
                    return TypeName(type.GetDeclaringType()) + "+" + reader.GetString(type.Name);
                string ns = reader.GetString(type.Namespace);
                return (ns.Length > 0 ? ns + "." : "") + reader.GetString(type.Name);
            }
            return "";
        }
        var members = new SortedSet<string>();
        foreach (var handle in reader.MemberReferences) {
            var member = reader.GetMemberReference(handle);
            string type = TypeName(member.Parent), name = reader.GetString(member.Name);
            if (targetTypes.Any(t => type.EndsWith("." + t)) || targetMethods.Contains(name))
                members.Add(type + "." + name);
        }
        var attributes = new List<object>();
        foreach (var handle in reader.TypeDefinitions) {
            var type = reader.GetTypeDefinition(handle);
            var mentions = new SortedSet<string>();
            foreach (var attrHandle in type.GetCustomAttributes()) {
                var attr = reader.GetCustomAttribute(attrHandle);
                if (attr.Constructor.Kind != HandleKind.MemberReference) continue;
                var ctor = reader.GetMemberReference((MemberReferenceHandle)attr.Constructor);
                if (TypeName(ctor.Parent) != "HarmonyLib.HarmonyPatch") continue;
                string blob = Encoding.UTF8.GetString(reader.GetBlobBytes(attr.Value));
                foreach (string needle in targetTypes.Concat(targetMethods))
                    if (blob.Contains(needle, StringComparison.Ordinal)) mentions.Add(needle);
            }
            if (mentions.Count > 0) attributes.Add(new {
                patchClass = TypeName(handle), mentions = mentions.ToArray()
            });
        }
        reports.Add(new {
            path, assembly = reader.GetString(reader.GetAssemblyDefinition().Name),
            assemblyReferences = reader.AssemblyReferences.Select(h => reader.GetString(reader.GetAssemblyReference(h).Name)).ToArray(),
            memberReferences = members.ToArray(), harmonyAttributeMentions = attributes.ToArray()
        });
    }
    catch (Exception ex) { reports.Add(new { path, error = ex.Message }); }
}
Console.WriteLine(JsonSerializer.Serialize(reports, new JsonSerializerOptions { WriteIndented = true }));
