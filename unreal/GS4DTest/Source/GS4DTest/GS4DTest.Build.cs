using UnrealBuildTool;
public class GS4DTest : ModuleRules { public GS4DTest(ReadOnlyTargetRules Target) : base(Target) { PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs; PublicDependencyModuleNames.AddRange(new[]{"Core","CoreUObject","Engine"}); } }
