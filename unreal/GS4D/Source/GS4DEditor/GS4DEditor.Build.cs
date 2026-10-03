using UnrealBuildTool;
public class GS4DEditor : ModuleRules
{
    public GS4DEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "UnrealEd", "GS4D", "AssetRegistry" });
    }
}
