#pragma once

#include "CoreMinimal.h"
#include "Components/MeshComponent.h"
#include "GameFramework/Actor.h"
#include "GS4DAsset.h"
#include "GS4DComponent.generated.h"

UCLASS(ClassGroup=Rendering, meta=(BlueprintSpawnableComponent))
class GS4D_API UGS4DComponent : public UMeshComponent
{
    GENERATED_BODY()
public:
    UGS4DComponent();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS") TObjectPtr<UGS4DAsset> Sequence;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="4DGS", meta=(ClampMin="0", ClampMax="1")) float NormalizedTime = 0;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS") bool bPlaying = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS") bool bLoop = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS", meta=(ClampMin="0")) float PlaybackRate = 1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS") bool bPreviewInEditor = false;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS", meta=(ClampMin="0")) int32 MaxPoints = 0;
    UFUNCTION(BlueprintCallable, Category="4DGS") void SetSequence(UGS4DAsset* Asset);
    UFUNCTION(BlueprintCallable, Category="4DGS") void SetNormalizedTime(float Time);
    UFUNCTION(BlueprintCallable, Category="4DGS") void Play() { bPlaying = true; }
    UFUNCTION(BlueprintCallable, Category="4DGS") void Pause() { bPlaying = false; }
    int32 FrameIndex() const;
    virtual FPrimitiveSceneProxy* CreateSceneProxy() override;
    virtual FBoxSphereBounds CalcBounds(const FTransform& LocalToWorld) const override;
    virtual int32 GetNumMaterials() const override { return 1; }
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* TickFunction) override;
#if WITH_EDITOR
    virtual void PostEditChangeProperty(FPropertyChangedEvent& Event) override;
#endif
private:
    int32 DisplayedFrame = INDEX_NONE;
};

UCLASS()
class GS4D_API AGS4DActor : public AActor
{
    GENERATED_BODY()
public:
    AGS4DActor();
    virtual bool ShouldTickIfViewportsOnly() const override { return true; }
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") TObjectPtr<UGS4DComponent> GaussianComponent;
};
