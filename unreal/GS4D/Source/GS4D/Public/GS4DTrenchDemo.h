#pragma once

#include "CoreMinimal.h"
#include "GS4DComponent.h"
#include "GameFramework/Character.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/HUD.h"
#include "GameFramework/PlayerController.h"
#include "GS4DTrenchDemo.generated.h"

class UCameraComponent;
class UPointLightComponent;

/** One-shot Gaussian playback with an explicitly authored, synchronized lighting envelope. */
UCLASS()
class GS4D_API AGS4DTrenchExplosion : public AGS4DActor
{
    GENERATED_BODY()
public:
    AGS4DTrenchExplosion();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") TObjectPtr<UPointLightComponent> FlashLight;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") TObjectPtr<UPointLightComponent> FireLight;
    /** Total one-shot length, including the final sampled image's hold. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench", meta=(ClampMin="0.01")) float PlaybackDuration = 1.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting", meta=(ClampMin="0")) float FlashPeakIntensity = 1600000.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting", meta=(ClampMin="0")) float FirePeakIntensity = 420000.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting") FLinearColor FlashColor = FLinearColor(1.f, .72f, .34f);
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting") FLinearColor FireColor = FLinearColor(1.f, .19f, .025f);
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting", meta=(ClampMin="1")) float FlashRadius = 3200.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench|Lighting", meta=(ClampMin="1")) float FireRadius = 2400.f;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") bool bExplosionActive = false;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") float ElapsedSeconds = 0.f;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") int32 TriggerCount = 0;

    UFUNCTION(BlueprintCallable, Category="4DGS Trench") void TriggerExplosion();
    UFUNCTION(BlueprintCallable, Category="4DGS Trench") void StopExplosion();
    UFUNCTION(BlueprintPure, Category="4DGS Trench") bool IsExplosionActive() const { return bExplosionActive; }
    UFUNCTION(BlueprintPure, Category="4DGS Trench") float GetExplosionElapsed() const { return ElapsedSeconds; }
private:
    void UpdateExplosion();
};

/** A colliding, gravity-driven first-person character; it needs no project input mappings. */
UCLASS()
class GS4D_API AGS4DTrenchCharacter : public ACharacter
{
    GENERATED_BODY()
public:
    AGS4DTrenchCharacter();
    virtual void OnConstruction(const FTransform& Transform) override;
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void SetupPlayerInputComponent(UInputComponent* Input) override;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="4DGS Trench") TObjectPtr<UCameraComponent> Camera;
    /** Linear body size relative to the original 176 cm character; the world keeps its authored scale. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="4DGS Trench|Player", meta=(ClampMin="0.1", ClampMax="2")) float CharacterScale = 2.f / 3.f;
    /** Reference-size speeds; effective movement speeds are multiplied by CharacterScale. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench", meta=(ClampMin="1")) float WalkSpeed = 300.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench", meta=(ClampMin="1")) float SprintSpeed = 520.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="4DGS Trench", meta=(ClampMin="0.01")) float MouseSensitivity = .2f;
    UFUNCTION(BlueprintCallable, Category="4DGS Trench") void TriggerExplosion();
private:
    void ApplyCharacterScale();
    void LookHorizontal(float Value);
    void LookVertical(float Value);
    void StartJump();
    void FinishJump();
    void ToggleCursor();
};

UCLASS()
class GS4D_API AGS4DTrenchController : public APlayerController
{
    GENERATED_BODY()
public:
    virtual void InitInputSystem() override;
    virtual void BeginPlay() override;
    virtual void AddYawInput(float Value) override;
    virtual void AddPitchInput(float Value) override;
};

UCLASS()
class GS4D_API AGS4DTrenchHUD : public AHUD
{
    GENERATED_BODY()
public:
    virtual void DrawHUD() override;
private:
    float SmoothedFrameSeconds = 0.f;
};

struct FGS4DTrenchValidationSample
{
    double Time = 0;
    float DeltaSeconds = 0;
    FVector Location = FVector::ZeroVector;
    FVector Velocity = FVector::ZeroVector;
    bool bGrounded = false;
    bool bGroundTrace = false;
    bool bActive = false;
    bool bHidden = true;
    float NormalizedTime = 0;
    float FlashIntensity = 0;
    float FireIntensity = 0;
    int32 FrameIndex = 0;
    int32 ProjectionFrameA = 0;
    int32 ProjectionFrameB = 0;
    float ProjectionAlpha = 0.f;
    int32 InterpolationCVar = -1;
    int32 Stage = 0;
    int32 TriggerCount = 0;
};

/** Trench rules also correct Pawn collision on the source map's exact large BasicShapes local-fog cube.
 * The visual MI_LocalVolFog enclosure alone is matched; walls, terrain and all other channels are preserved. */
UCLASS()
class GS4D_API AGS4DTrenchGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    AGS4DTrenchGameMode();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual APawn* SpawnDefaultPawnAtTransform_Implementation(AController* NewPlayer, const FTransform& SpawnTransform) override;
    FString ValidationStatus;
private:
    /** The source trench map uses one large BasicShapes cube as a local volumetric fog enclosure.
     * Its inherited BlockAll collision must ignore Pawn before spawning; real trench geometry keeps its collision. */
    void ConfigureVisualFogCollision();
    void TickValidation(float DeltaSeconds);
    void CaptureValidation(const FString& Name);
    void SaveValidation();
    bool bValidating = false;
    bool bValidationFinished = false;
    bool bValidationLookLocked = false;
    bool bExitValidation = false;
    bool bIdleOff = false;
    bool bGroundedInitially = false;
    bool bInitialSceneStateRecorded = false;
    bool bInitialFloorBlocking = false;
    bool bInitialFloorWalkable = false;
    FVector InitialPlayerLocation = FVector::ZeroVector;
    float InitialCharacterScale = 0.f;
    float InitialCapsuleRadius = 0.f;
    float InitialCapsuleHalfHeight = 0.f;
    FVector InitialCameraRelativeLocation = FVector::ZeroVector;
    float InitialCameraHeightAboveFloor = 0.f;
    float InitialCapsuleBottomAboveFloor = 0.f;
    FVector InitialCameraLocation = FVector::ZeroVector;
    FRotator InitialCameraRotation = FRotator::ZeroRotator;
    FVector InitialFloorImpactPoint = FVector::ZeroVector;
    float InitialFloorDistance = 0.f;
    FString InitialFloorActorPath;
    FString InitialFloorComponentPath;
    bool bOneShotStopped = false;
    bool bRetriggerRestarted = false;
    bool bJumpReleased = false;
    bool bFlashCaptured = false;
    bool bFireCaptured = false;
    int32 ValidationStage = 0;
    double ValidationStarted = 0;
    double StageStarted = 0;
    FVector MovementStart = FVector::ZeroVector;
    FVector JumpStart = FVector::ZeroVector;
    float MovementDistance = 0.f;
    float MaximumJumpHeight = 0.f;
    float MaximumFlashIntensity = 0.f;
    float MaximumFireIntensity = 0.f;
    float MouseYawChange = 0.f;
    float MousePitchChange = 0.f;
    FRotator ValidationViewRotation = FRotator::ZeroRotator;
    bool bSpawnAttempted = false;
    bool bLastSpawnSucceeded = false;
    FVector LastSpawnLocation = FVector::ZeroVector;
    FVector LastSpawnActualLocation = FVector::ZeroVector;
    FRotator LastSpawnRotation = FRotator::ZeroRotator;
    FString LastSpawnPawnClass;
    FString LastSpawnDiagnosis = TEXT("No default-pawn spawn has been attempted");
    TArray<FString> LastSpawnBlockers;
    bool bVisualFogCollisionChecked = false;
    int32 VisualFogMatchedCount = 0;
    int32 VisualFogCollisionFixCount = 0;
    TArray<FString> VisualFogComponentPaths;
    FString ValidationFolder;
    TArray<FGS4DTrenchValidationSample> ValidationSamples;
    TArray<FString> ValidationScreenshots;
};
