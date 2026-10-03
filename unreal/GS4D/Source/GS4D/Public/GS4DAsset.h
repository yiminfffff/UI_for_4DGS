#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "GS4DAsset.generated.h"

UCLASS(BlueprintType)
class GS4D_API UGS4DAsset : public UDataAsset
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="4DGS") TObjectPtr<UMaterialInterface> SplatMaterial;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") int32 PointCount = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") int32 FrameCount = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") int32 SHDegree = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") float SourceFPS = 24;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS") float DurationSeconds = 1;
    UPROPERTY() TArray<float> Times;
    UPROPERTY() TArray<uint8> FrameData;
    UPROPERTY() FBox LocalBounds = FBox(FVector(-100), FVector(100));
    UPROPERTY(VisibleAnywhere, Category="4DGS") FString SourceFile;
    static constexpr int32 FloatsPerPoint = 58;
};
