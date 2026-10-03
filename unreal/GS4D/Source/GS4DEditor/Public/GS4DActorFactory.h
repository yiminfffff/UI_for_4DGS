#pragma once
#include "CoreMinimal.h"
#include "ActorFactories/ActorFactory.h"
#include "GS4DActorFactory.generated.h"

UCLASS()
class UGS4DActorFactory : public UActorFactory
{
    GENERATED_BODY()
public:
    UGS4DActorFactory();
    virtual bool CanCreateActorFrom(const FAssetData& AssetData, FText& Error) override;
    virtual UObject* GetAssetFromActorInstance(AActor* Actor) override;
protected:
    virtual void PostSpawnActor(UObject* Asset, AActor* Actor) override;
};
