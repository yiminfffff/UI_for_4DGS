#pragma once

#include "CoreMinimal.h"
#include "GameFramework/DefaultPawn.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/HUD.h"
#include "GameFramework/PlayerController.h"
#include "GS4DPreview.generated.h"

UCLASS()
class GS4D_API AGS4DPreviewPawn : public ADefaultPawn
{
    GENERATED_BODY()
public:
    AGS4DPreviewPawn();
    virtual void Tick(float DeltaSeconds) override;
    virtual void SetupPlayerInputComponent(UInputComponent* Input) override;
    UFUNCTION(BlueprintCallable, Category="4DGS Preview") void FocusEffect();
    void TogglePlayback();
    void RestartPlayback();
private:
    void LookHorizontal(float Value);
    void LookVertical(float Value);
    void ToggleCursor();
    void ToggleStats();
    void Benchmark();
    void ExitPreview();
};

UCLASS()
class GS4D_API AGS4DPreviewController : public APlayerController
{
    GENERATED_BODY()
public:
    virtual void BeginPlay() override;
};

UCLASS()
class GS4D_API AGS4DPreviewHUD : public AHUD
{
    GENERATED_BODY()
public:
    virtual void DrawHUD() override;
    bool bShowStats = true;
private:
    float SmoothedFrameMS = 0;
};

struct FGS4DPreviewSample
{
    double FrameMS = 0, GameMS = 0, RenderMS = 0, RHIMS = 0, GPUMS = 0;
    double MemoryMB = 0, Time = 0;
    int32 AnimationFrame = 0;
};

UCLASS()
class GS4D_API AGS4DPreviewGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    AGS4DPreviewGameMode();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    UFUNCTION(BlueprintCallable, Category="4DGS Preview") void StartBenchmark();
    FString BenchmarkStatus;
private:
    void SetPhase(int32 Index);
    void SaveBenchmark();
    void InputSmokeTest(double Elapsed);
    bool bBenchmarking = false;
    int32 Phase = -1, InputStep = 0;
    double Started = 0, PhaseStarted = 0, PreviousTick = 0;
    FVector InputStart = FVector::ZeroVector;
    double ForwardDistance = 0, RightDistance = 0;
    float InitialYaw = 0, YawChange = 0;
    bool bSpacePauses = false, bRestartWorks = false;
    bool bScreenshotTaken = false;
    FString OutputFolder;
    TArray<TArray<FGS4DPreviewSample>> Samples;
};
