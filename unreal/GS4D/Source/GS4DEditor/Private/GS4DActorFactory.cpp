#include "GS4DActorFactory.h"
#include "GS4DComponent.h"
#include "AssetRegistry/AssetData.h"

UGS4DActorFactory::UGS4DActorFactory()
{
    DisplayName = FText::FromString(TEXT("4D Gaussian Sequence"));
    NewActorClass = AGS4DActor::StaticClass();
}
bool UGS4DActorFactory::CanCreateActorFrom(const FAssetData& Data, FText& Error)
{
    return Data.IsValid() && Data.GetClass() && Data.GetClass()->IsChildOf(UGS4DAsset::StaticClass());
}
void UGS4DActorFactory::PostSpawnActor(UObject* Asset, AActor* Actor)
{
    if (AGS4DActor* Gaussian = Cast<AGS4DActor>(Actor)) Gaussian->GaussianComponent->SetSequence(Cast<UGS4DAsset>(Asset));
}
UObject* UGS4DActorFactory::GetAssetFromActorInstance(AActor* Actor)
{
    if (AGS4DActor* Gaussian = Cast<AGS4DActor>(Actor)) return Gaussian->GaussianComponent->Sequence;
    return nullptr;
}
