using UnrealBuildTool;
public class GS4DTestEditorTarget : TargetRules { public GS4DTestEditorTarget(TargetInfo Target) : base(Target) { Type=TargetType.Editor; DefaultBuildSettings=BuildSettingsVersion.Latest; IncludeOrderVersion=EngineIncludeOrderVersion.Latest; ExtraModuleNames.Add("GS4DTest"); } }
