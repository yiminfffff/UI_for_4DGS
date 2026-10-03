using UnrealBuildTool;
public class GS4DTestTarget : TargetRules { public GS4DTestTarget(TargetInfo Target) : base(Target) { Type=TargetType.Game; DefaultBuildSettings=BuildSettingsVersion.Latest; IncludeOrderVersion=EngineIncludeOrderVersion.Latest; ExtraModuleNames.Add("GS4DTest"); } }
