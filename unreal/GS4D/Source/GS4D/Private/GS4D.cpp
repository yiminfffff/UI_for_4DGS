#include "Modules/ModuleManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "ShaderCore.h"

class FGS4DModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("GS4D"));
        if (Plugin.IsValid())
            AddShaderSourceDirectoryMapping(TEXT("/Plugin/GS4D"), FPaths::Combine(Plugin->GetBaseDir(), TEXT("Shaders")));
    }
};

IMPLEMENT_MODULE(FGS4DModule, GS4D)
