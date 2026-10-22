#include "GS4DTrenchDemo.h"

#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/CapsuleComponent.h"
#include "Components/InputComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Canvas.h"
#include "Engine/OverlapResult.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerInput.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Materials/MaterialInterface.h"
#include "Serialization/JsonSerializer.h"
#include "UnrealClient.h"

DEFINE_LOG_CATEGORY_STATIC(LogGS4DTrench, Log, All);

namespace
{
AGS4DTrenchExplosion* FindExplosion(UWorld* World)
{
    for (TActorIterator<AGS4DTrenchExplosion> It(World); It; ++It) return *It;
    return nullptr;
}

void SendValidationKey(APlayerController* PC, const FKey& Key, EInputEvent Event)
{
    PC->InputKey(FInputKeyEventArgs(nullptr, FInputDeviceId::CreateFromInternalId(0),
        Key, Event, Event == IE_Released ? 0.f : 1.f, false, FPlatformTime::Cycles64()));
}

void SendValidationMouse(APlayerController* PC, const FKey& Key, float Delta)
{
    PC->InputKey(FInputKeyEventArgs(nullptr, FInputDeviceId::CreateFromInternalId(0),
        Key, Delta, 1.f / 60.f, 1, FPlatformTime::Cycles64()));
}

TArray<TSharedPtr<FJsonValue>> VectorJson(const FVector& Vector)
{
    return { MakeShared<FJsonValueNumber>(Vector.X), MakeShared<FJsonValueNumber>(Vector.Y),
        MakeShared<FJsonValueNumber>(Vector.Z) };
}

bool LightsOff(const AGS4DTrenchExplosion* Effect)
{
    return Effect && Effect->FlashLight->Intensity == 0.f && Effect->FireLight->Intensity == 0.f
        && !Effect->FlashLight->IsVisible() && !Effect->FireLight->IsVisible();
}

TSharedRef<FJsonObject> FrameTimingJson(TArray<float> FrameSeconds)
{
    const TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    double Duration = 0.0;
    for (const float Seconds : FrameSeconds) Duration += Seconds;
    Result->SetNumberField(TEXT("sample_count"), FrameSeconds.Num());
    Result->SetNumberField(TEXT("summed_frame_seconds"), Duration);
    Result->SetNumberField(TEXT("mean_fps"), Duration > 0.0 ? FrameSeconds.Num() / Duration : 0.0);
    Result->SetNumberField(TEXT("mean_frame_ms"), FrameSeconds.Num() ? Duration * 1000.0 / FrameSeconds.Num() : 0.0);
    FrameSeconds.Sort();
    const int32 P95Index = FrameSeconds.IsEmpty() ? 0 : FMath::Clamp(FMath::CeilToInt(FrameSeconds.Num() * .95f) - 1, 0, FrameSeconds.Num() - 1);
    Result->SetNumberField(TEXT("p95_frame_ms"), FrameSeconds.IsValidIndex(P95Index) ? FrameSeconds[P95Index] * 1000.f : 0.f);
    return Result;
}
}

AGS4DTrenchExplosion::AGS4DTrenchExplosion()
{
    PrimaryActorTick.bCanEverTick = true;
    GaussianComponent->bPlaying = false;
    GaussianComponent->bLoop = false;
    GaussianComponent->bPreviewInEditor = false;
    SetActorHiddenInGame(true);

    FlashLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("ExplosionFlash"));
    FlashLight->SetupAttachment(RootComponent);
    FlashLight->SetMobility(EComponentMobility::Movable);
    FlashLight->IntensityUnits = ELightUnits::Lumens;
    FlashLight->SetIntensity(0.f);
    FlashLight->SetVisibility(false);
    FlashLight->SetAttenuationRadius(FlashRadius);
    FlashLight->SetSourceRadius(65.f);
    FlashLight->SetCastShadows(true);
    FlashLight->SetLightColor(FlashColor);
    FlashLight->SetVolumetricScatteringIntensity(.25f);

    FireLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("ExplosionFireFill"));
    FireLight->SetupAttachment(RootComponent);
    FireLight->SetMobility(EComponentMobility::Movable);
    FireLight->IntensityUnits = ELightUnits::Lumens;
    FireLight->SetIntensity(0.f);
    FireLight->SetVisibility(false);
    FireLight->SetAttenuationRadius(FireRadius);
    FireLight->SetSourceRadius(140.f);
    FireLight->SetCastShadows(false);
    FireLight->SetLightColor(FireColor);
    FireLight->SetVolumetricScatteringIntensity(.2f);
}

void AGS4DTrenchExplosion::BeginPlay()
{
    Super::BeginPlay();
    // The assigned sequence owns its material; refresh any stale serialized component override.
    GaussianComponent->SetSequence(GaussianComponent->Sequence.Get());
    // This actor owns the clock so a final-sample hold and the lighting cannot drift apart.
    GaussianComponent->SetComponentTickEnabled(false);
    FlashLight->SetAttenuationRadius(FlashRadius);
    FireLight->SetAttenuationRadius(FireRadius);
    StopExplosion();
    GaussianComponent->SetNormalizedTime(0.f);
}

void AGS4DTrenchExplosion::TriggerExplosion()
{
    if (!GaussianComponent->Sequence || GaussianComponent->Sequence->FrameCount <= 0)
    {
        UE_LOG(LogGS4DTrench, Warning, TEXT("Explosion has no valid Gaussian sequence: %s"), *GetName());
        return;
    }
    ++TriggerCount;
    ElapsedSeconds = 0.f;
    bExplosionActive = true;
    GaussianComponent->bLoop = false;
    GaussianComponent->bPlaying = true;
    GaussianComponent->SetNormalizedTime(0.f);
    GaussianComponent->SetVisibility(true);
    SetActorHiddenInGame(false);
    UpdateExplosion();
    UE_LOG(LogGS4DTrench, Log, TEXT("Q explosion trigger %d (%s)"), TriggerCount, *GetName());
}

void AGS4DTrenchExplosion::StopExplosion()
{
    bExplosionActive = false;
    GaussianComponent->bPlaying = false;
    SetActorHiddenInGame(true);
    FlashLight->SetIntensity(0.f);
    FireLight->SetIntensity(0.f);
    FlashLight->SetVisibility(false);
    FireLight->SetVisibility(false);
}

void AGS4DTrenchExplosion::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (!bExplosionActive) return;
    ElapsedSeconds += DeltaSeconds;
    if (ElapsedSeconds >= FMath::Max(PlaybackDuration, .01f))
    {
        GaussianComponent->SetNormalizedTime(1.f);
        StopExplosion();
        return;
    }
    UpdateExplosion();
}

void AGS4DTrenchExplosion::UpdateExplosion()
{
    const UGS4DAsset* Sequence = GaussianComponent->Sequence;
    float LastHold = Sequence ? 1.f / FMath::Max(Sequence->SourceFPS, 1.f) : .125f;
    if (Sequence && Sequence->Times.Num() > 1)
    {
        const int32 Last = Sequence->Times.Num() - 1;
        LastHold = FMath::Max(0.f, Sequence->Times[Last] - Sequence->Times[Last - 1]) * Sequence->DurationSeconds;
    }
    LastHold = FMath::Clamp(LastHold, 0.f, PlaybackDuration * .5f);
    const float SampledSpan = FMath::Max(PlaybackDuration - LastHold, .001f);
    GaussianComponent->SetNormalizedTime(FMath::Clamp(ElapsedSeconds / SampledSpan, 0.f, 1.f));

    const float T = ElapsedSeconds;
    const float Flash = T < .035f ? FMath::Lerp(.6f, 1.f, T / .035f)
        : (T < .55f ? FMath::Exp(-(T - .035f) * 11.f) : 0.f);
    const float Flicker = .86f + .09f * FMath::Sin(T * 37.f) + .05f * FMath::Sin(T * 79.f);
    const float Tail = FMath::Clamp((PlaybackDuration - T) / .35f, 0.f, 1.f);
    const float Fire = FMath::Min(T / .09f, 1.f) * FMath::Exp(-T * 2.2f) * Flicker * Tail;
    FlashLight->SetLightColor(FMath::Lerp(FlashColor, FireColor, FMath::Clamp(T * 2.f, 0.f, 1.f)));
    FireLight->SetLightColor(FireColor);
    FlashLight->SetIntensity(FlashPeakIntensity * Flash);
    FireLight->SetIntensity(FirePeakIntensity * Fire);
    FlashLight->SetVisibility(Flash > .0001f);
    FireLight->SetVisibility(Fire > .0001f);
}

AGS4DTrenchCharacter::AGS4DTrenchCharacter()
{
    PrimaryActorTick.bCanEverTick = true;
    GetCapsuleComponent()->SetCollisionProfileName(TEXT("Pawn"));
    GetMesh()->SetVisibility(false);
    GetMesh()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    bUseControllerRotationYaw = true;
    bUseControllerRotationPitch = false;
    bUseControllerRotationRoll = false;

    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("FirstPersonCamera"));
    Camera->SetupAttachment(GetCapsuleComponent());
    Camera->bUsePawnControlRotation = true;
    Camera->bLockToHmd = false;
    Camera->FieldOfView = 80.f;

    UCharacterMovementComponent* Movement = GetCharacterMovement();
    Movement->bOrientRotationToMovement = false;
    Movement->SetWalkableFloorAngle(48.f);
    Movement->GravityScale = 1.2f;
    Movement->AirControl = .2f;
    // The CDO must already expose the reduced capsule to collision-aware spawn diagnostics.
    ApplyCharacterScale();
}

void AGS4DTrenchCharacter::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    ApplyCharacterScale();
}

void AGS4DTrenchCharacter::BeginPlay()
{
    Super::BeginPlay();
    // Serialized Blueprint defaults can arrive after the native constructor.
    ApplyCharacterScale();
}

void AGS4DTrenchCharacter::ApplyCharacterScale()
{
    CharacterScale = FMath::Clamp(CharacterScale, .1f, 2.f);
    GetCapsuleComponent()->SetCapsuleSize(34.f * CharacterScale, 88.f * CharacterScale);
    BaseEyeHeight = 68.f * CharacterScale;
    if (Camera) Camera->SetRelativeLocation(FVector(0.f, 0.f, BaseEyeHeight));
    UCharacterMovementComponent* Movement = GetCharacterMovement();
    Movement->MaxWalkSpeed = WalkSpeed * CharacterScale;
    Movement->MaxStepHeight = 45.f * CharacterScale;
    // With unchanged gravity, sqrt(scale) produces a jump height proportional to body size.
    Movement->JumpZVelocity = 430.f * FMath::Sqrt(CharacterScale);
    Movement->BrakingDecelerationWalking = 2000.f * CharacterScale;
}

void AGS4DTrenchCharacter::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    APlayerController* PC = Cast<APlayerController>(Controller);
    if (!PC || !PC->IsLocalController() || PC->bShowMouseCursor) return;
    const FRotator YawRotation(0.f, PC->GetControlRotation().Yaw, 0.f);
    const float Forward = float(PC->IsInputKeyDown(EKeys::W)) - float(PC->IsInputKeyDown(EKeys::S));
    const float Right = float(PC->IsInputKeyDown(EKeys::D)) - float(PC->IsInputKeyDown(EKeys::A));
    FVector Direction = YawRotation.Vector() * Forward + FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y) * Right;
    AddMovementInput(Direction.GetClampedToMaxSize(1.f));
    GetCharacterMovement()->MaxWalkSpeed = (PC->IsInputKeyDown(EKeys::LeftShift) ? SprintSpeed : WalkSpeed) * CharacterScale;
}

void AGS4DTrenchCharacter::SetupPlayerInputComponent(UInputComponent* Input)
{
    Super::SetupPlayerInputComponent(Input);
    Input->BindAxisKey(EKeys::MouseX, this, &AGS4DTrenchCharacter::LookHorizontal);
    Input->BindAxisKey(EKeys::MouseY, this, &AGS4DTrenchCharacter::LookVertical);
    Input->BindKey(EKeys::Q, IE_Pressed, this, &AGS4DTrenchCharacter::TriggerExplosion);
    Input->BindKey(EKeys::SpaceBar, IE_Pressed, this, &AGS4DTrenchCharacter::StartJump);
    Input->BindKey(EKeys::SpaceBar, IE_Released, this, &AGS4DTrenchCharacter::FinishJump);
    Input->BindKey(EKeys::F1, IE_Pressed, this, &AGS4DTrenchCharacter::ToggleCursor);
    Input->BindKey(EKeys::Escape, IE_Pressed, this, &AGS4DTrenchCharacter::ToggleCursor);
}

void AGS4DTrenchCharacter::LookHorizontal(float Value)
{
    const APlayerController* PC = Cast<APlayerController>(Controller);
    if (PC && !PC->bShowMouseCursor) AddControllerYawInput(Value * MouseSensitivity);
}

void AGS4DTrenchCharacter::LookVertical(float Value)
{
    const APlayerController* PC = Cast<APlayerController>(Controller);
    // FSceneViewport already negates screen-space Y: positive MouseY means looking up.
    if (PC && !PC->bShowMouseCursor) AddControllerPitchInput(Value * MouseSensitivity);
}

void AGS4DTrenchCharacter::StartJump()
{
    const APlayerController* PC = Cast<APlayerController>(Controller);
    if (PC && !PC->bShowMouseCursor) Jump();
}

void AGS4DTrenchCharacter::FinishJump() { StopJumping(); }

void AGS4DTrenchCharacter::TriggerExplosion()
{
    const APlayerController* PC = Cast<APlayerController>(Controller);
    if (PC && PC->bShowMouseCursor) return;
    for (TActorIterator<AGS4DTrenchExplosion> It(GetWorld()); It; ++It) It->TriggerExplosion();
}

void AGS4DTrenchCharacter::ToggleCursor()
{
    if (APlayerController* PC = Cast<APlayerController>(Controller))
    {
        PC->bShowMouseCursor = !PC->bShowMouseCursor;
        if (PC->bShowMouseCursor) PC->SetInputMode(FInputModeGameAndUI());
        else PC->SetInputMode(FInputModeGameOnly());
    }
}

void AGS4DTrenchController::InitInputSystem()
{
    Super::InitInputSystem();
    if (!PlayerInput) return;
    for (const FKey& Key : { EKeys::MouseX, EKeys::MouseY })
    {
        FInputAxisProperties Properties;
        PlayerInput->GetAxisProperties(Key, Properties);
        Properties.DeadZone = 0.f;
        Properties.Exponent = 1.f;
        Properties.Sensitivity = 1.f;
        Properties.bInvert = false;
        PlayerInput->SetAxisProperties(Key, Properties);
    }
}

void AGS4DTrenchController::AddYawInput(float Value)
{
    // This controller's raw mouse bindings supply degrees; inherited legacy scales are unrelated.
    if (!IsLookInputIgnored()) RotationInput.Yaw += Value;
}

void AGS4DTrenchController::AddPitchInput(float Value)
{
    if (!IsLookInputIgnored()) RotationInput.Pitch += Value;
}

void AGS4DTrenchController::BeginPlay()
{
    Super::BeginPlay();
    bShowMouseCursor = false;
    SetInputMode(FInputModeGameOnly());
    if (PlayerCameraManager)
    {
        PlayerCameraManager->ViewPitchMin = -80.f;
        PlayerCameraManager->ViewPitchMax = 80.f;
    }
}

void AGS4DTrenchHUD::DrawHUD()
{
    Super::DrawHUD();
    if (!Canvas) return;
    const float Delta = GetWorld()->GetDeltaSeconds();
    SmoothedFrameSeconds = SmoothedFrameSeconds > 0.f ? FMath::Lerp(SmoothedFrameSeconds, Delta, .05f) : Delta;
    const float Width = Canvas->SizeX;
    const float Height = Canvas->SizeY;
    const AGS4DTrenchExplosion* Effect = FindExplosion(GetWorld());
    const bool bActive = Effect && Effect->bExplosionActive;
    const FLinearColor Accent = bActive ? FLinearColor(1.f, .49f, .18f) : FLinearColor(.76f, .84f, .78f);
    DrawRect(FLinearColor(.008f, .012f, .009f, .65f), 24.f, Height - 94.f, 650.f, 70.f);
    DrawText(TEXT("Q  DETONATE"), Accent, 38.f, Height - 84.f, nullptr, 1.2f);
    DrawText(TEXT("WASD  Move    Mouse  Look    Shift  Sprint    Space  Jump    F1  Cursor"),
        FLinearColor(.85f, .86f, .82f), 38.f, Height - 57.f);
    DrawText(FString::Printf(TEXT("4DGS  /  %s  /  %.0f FPS"), bActive ? TEXT("DETONATING") : TEXT("READY"),
        1.f / FMath::Max(SmoothedFrameSeconds, .001f)), Accent, 26.f, 24.f);
    DrawRect(FLinearColor(1.f, 1.f, 1.f, .65f), Width * .5f - 1.f, Height * .5f - 1.f, 2.f, 2.f);
    if (const AGS4DTrenchGameMode* Mode = GetWorld()->GetAuthGameMode<AGS4DTrenchGameMode>())
        if (!Mode->ValidationStatus.IsEmpty()) DrawText(Mode->ValidationStatus, FLinearColor::Yellow, 26.f, 48.f);
}

AGS4DTrenchGameMode::AGS4DTrenchGameMode()
{
    DefaultPawnClass = AGS4DTrenchCharacter::StaticClass();
    PlayerControllerClass = AGS4DTrenchController::StaticClass();
    HUDClass = AGS4DTrenchHUD::StaticClass();
    PrimaryActorTick.bCanEverTick = true;
}

APawn* AGS4DTrenchGameMode::SpawnDefaultPawnAtTransform_Implementation(AController* NewPlayer, const FTransform& SpawnTransform)
{
    ConfigureVisualFogCollision();
    bSpawnAttempted = true;
    LastSpawnLocation = SpawnTransform.GetLocation();
    LastSpawnRotation = SpawnTransform.Rotator();
    LastSpawnBlockers.Reset();
    const UClass* PawnClass = GetDefaultPawnClassForController(NewPlayer);
    LastSpawnPawnClass = PawnClass ? PawnClass->GetPathName() : TEXT("<none>");
    const ACharacter* DefaultCharacter = PawnClass ? Cast<ACharacter>(PawnClass->GetDefaultObject()) : nullptr;
    if (DefaultCharacter)
    {
        const UCapsuleComponent* Capsule = DefaultCharacter->GetCapsuleComponent();
        TArray<FOverlapResult> Overlaps;
        FCollisionQueryParams Query(SCENE_QUERY_STAT(GS4DTrenchSpawn), false, NewPlayer);
        GetWorld()->OverlapMultiByProfile(Overlaps, LastSpawnLocation, SpawnTransform.GetRotation(),
            Capsule->GetCollisionProfileName(), FCollisionShape::MakeCapsule(
                Capsule->GetScaledCapsuleRadius(), Capsule->GetScaledCapsuleHalfHeight()), Query);
        for (const FOverlapResult& Overlap : Overlaps)
        {
            if (Overlap.bBlockingHit)
                LastSpawnBlockers.AddUnique(FString::Printf(TEXT("%s | %s"),
                    *GetPathNameSafe(Overlap.GetActor()), *GetPathNameSafe(Overlap.GetComponent())));
        }
    }

    // Preserve the engine's collision-aware spawn and placement policy exactly.
    APawn* Result = Super::SpawnDefaultPawnAtTransform_Implementation(NewPlayer, SpawnTransform);
    bLastSpawnSucceeded = IsValid(Result);
    LastSpawnActualLocation = bLastSpawnSucceeded ? Result->GetActorLocation() : FVector::ZeroVector;
    LastSpawnDiagnosis = bLastSpawnSucceeded ? TEXT("Default pawn spawned using the engine collision-aware placement policy")
        : (LastSpawnBlockers.IsEmpty() ? TEXT("Engine rejected default pawn spawn; no blocking capsule overlap was returned by the diagnostic query")
            : TEXT("Engine rejected default pawn spawn; the requested capsule overlaps blocking scene geometry"));
    if (!bLastSpawnSucceeded)
        UE_LOG(LogGS4DTrench, Warning, TEXT("%s at %s, pawn %s, blockers: %s"), *LastSpawnDiagnosis,
            *LastSpawnLocation.ToString(), *LastSpawnPawnClass, *FString::Join(LastSpawnBlockers, TEXT("; ")));
    return Result;
}

void AGS4DTrenchGameMode::ConfigureVisualFogCollision()
{
    if (bVisualFogCollisionChecked) return;
    bVisualFogCollisionChecked = true;
    for (TActorIterator<AStaticMeshActor> It(GetWorld()); It; ++It)
    {
        UStaticMeshComponent* Component = It->GetStaticMeshComponent();
        if (!Component || !Component->GetStaticMesh()
            || Component->GetStaticMesh()->GetPathName() != TEXT("/Engine/BasicShapes/Cube.Cube")) continue;
        const FVector Extent = Component->Bounds.BoxExtent;
        if (Extent.X <= 500.f || Extent.Y <= 1000.f || Extent.Z <= 100.f) continue;
        bool bVisualLocalFog = false;
        for (int32 MaterialIndex = 0; MaterialIndex < Component->GetNumMaterials(); ++MaterialIndex)
        {
            const UMaterialInterface* Material = Component->GetMaterial(MaterialIndex);
            if (Material && Material->GetPathName() == TEXT("/Game/MilitaryTrench/Materials/MaterialInstances/MI_LocalVolFog.MI_LocalVolFog"))
                bVisualLocalFog = true;
        }
        if (!bVisualLocalFog) continue;
        ++VisualFogMatchedCount;
        VisualFogComponentPaths.Add(Component->GetPathName());
        if (Component->GetCollisionResponseToChannel(ECC_Pawn) != ECR_Ignore)
        {
            // Change this visual enclosure's Pawn filter alone; preserve every other collision channel.
            Component->SetCollisionResponseToChannel(ECC_Pawn, ECR_Ignore);
            ++VisualFogCollisionFixCount;
        }
    }
    UE_LOG(LogGS4DTrench, Log, TEXT("Visual local-fog collision: %d exact cube/material matches, %d Pawn responses changed to Ignore; %s"),
        VisualFogMatchedCount, VisualFogCollisionFixCount, *FString::Join(VisualFogComponentPaths, TEXT("; ")));
}

void AGS4DTrenchGameMode::BeginPlay()
{
    Super::BeginPlay();
    bValidating = FParse::Param(FCommandLine::Get(), TEXT("GS4DTrenchValidate"));
    bExitValidation = bValidating && FParse::Param(FCommandLine::Get(), TEXT("GS4DTrenchValidateExit"));
    if (!bValidating) return;
    ValidationStarted = StageStarted = GetWorld()->GetTimeSeconds();
    ValidationFolder = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("GS4DTrenchValidation"),
        FDateTime::Now().ToString(TEXT("%Y%m%d-%H%M%S")));
    FParse::Value(FCommandLine::Get(), TEXT("GS4DTrenchValidationDir="), ValidationFolder);
    ValidationFolder = FPaths::ConvertRelativePathToFull(ValidationFolder);
    IFileManager::Get().MakeDirectory(*ValidationFolder, true);
    ValidationStatus = TEXT("Validation: settling scene");
    UE_LOG(LogGS4DTrench, Log, TEXT("Trench validation output: %s"), *ValidationFolder);
}

void AGS4DTrenchGameMode::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (bValidating) TickValidation(DeltaSeconds);
}

void AGS4DTrenchGameMode::CaptureValidation(const FString& Name)
{
    const FString Filename = FPaths::Combine(ValidationFolder, Name + TEXT(".png"));
    FScreenshotRequest::RequestScreenshot(Filename, true, false);
    ValidationScreenshots.Add(Filename);
}

void AGS4DTrenchGameMode::TickValidation(float DeltaSeconds)
{
    const double Now = GetWorld()->GetTimeSeconds();
    if (bValidationFinished)
    {
        if (bExitValidation && Now - StageStarted > 1.0 && GetWorld()->WorldType != EWorldType::PIE)
            FPlatformMisc::RequestExit(false);
        return;
    }
    APlayerController* PC = GetWorld()->GetFirstPlayerController();
    AGS4DTrenchCharacter* Character = PC ? Cast<AGS4DTrenchCharacter>(PC->GetPawn()) : nullptr;
    AGS4DTrenchExplosion* Effect = FindExplosion(GetWorld());
    if (!PC || !Character || !Effect)
    {
        if (Now - ValidationStarted > 20.0)
        {
            ValidationStatus = TEXT("Validation FAILED: missing trench character or explosion");
            SaveValidation();
            bValidationFinished = true;
            StageStarted = Now;
        }
        return;
    }
    // Opt-in validation compares the same viewpoint after its dedicated mouse-input test.
    // Normal gameplay never enters this branch or suppresses the player's mouse.
    if (bValidationLookLocked) PC->SetControlRotation(ValidationViewRotation);

    FGS4DTrenchValidationSample Sample;
    Sample.Time = Now - ValidationStarted;
    Sample.DeltaSeconds = DeltaSeconds;
    Sample.Location = Character->GetActorLocation();
    Sample.Velocity = Character->GetVelocity();
    Sample.bGrounded = Character->GetCharacterMovement()->IsMovingOnGround();
    FHitResult GroundHit;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(GS4DTrenchFloor), false, Character);
    Sample.bGroundTrace = GetWorld()->LineTraceSingleByChannel(GroundHit, Sample.Location,
        Sample.Location - FVector(0.f, 0.f, 250.f), ECC_Visibility, Query);
    Sample.bActive = Effect->bExplosionActive;
    Sample.bHidden = Effect->IsHidden();
    Sample.NormalizedTime = Effect->GaussianComponent->NormalizedTime;
    Sample.FrameIndex = Effect->GaussianComponent->FrameIndex();
    Effect->GaussianComponent->GetInterpolationState(Sample.ProjectionFrameA, Sample.ProjectionFrameB, Sample.ProjectionAlpha);
    static const IConsoleVariable* Interpolation = IConsoleManager::Get().FindConsoleVariable(TEXT("r.GS4D.Interpolate"));
    Sample.InterpolationCVar = Interpolation ? Interpolation->GetInt() : -1;
    Sample.Stage = ValidationStage;
    Sample.FlashIntensity = Effect->FlashLight->Intensity;
    Sample.FireIntensity = Effect->FireLight->Intensity;
    Sample.TriggerCount = Effect->TriggerCount;
    ValidationSamples.Add(Sample);
    MaximumFlashIntensity = FMath::Max(MaximumFlashIntensity, Sample.FlashIntensity);
    MaximumFireIntensity = FMath::Max(MaximumFireIntensity, Sample.FireIntensity);

    const double StageTime = Now - StageStarted;
    if (ValidationStage == 0 && StageTime >= 10.0)
    {
        bIdleOff = !Effect->bExplosionActive && Effect->IsHidden() && LightsOff(Effect);
        const FFindFloorResult& Floor = Character->GetCharacterMovement()->CurrentFloor;
        bInitialSceneStateRecorded = true;
        InitialPlayerLocation = Character->GetActorLocation();
        InitialCharacterScale = Character->CharacterScale;
        InitialCapsuleRadius = Character->GetCapsuleComponent()->GetScaledCapsuleRadius();
        InitialCapsuleHalfHeight = Character->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
        InitialCameraRelativeLocation = Character->Camera->GetRelativeLocation();
        InitialCameraLocation = Character->Camera->GetComponentLocation();
        InitialCameraRotation = Character->Camera->GetComponentRotation();
        bInitialFloorBlocking = Floor.bBlockingHit;
        bInitialFloorWalkable = Floor.IsWalkableFloor();
        InitialFloorActorPath = GetPathNameSafe(Floor.HitResult.GetActor());
        InitialFloorComponentPath = GetPathNameSafe(Floor.HitResult.GetComponent());
        InitialFloorImpactPoint = Floor.HitResult.ImpactPoint;
        InitialFloorDistance = Floor.GetDistanceToFloor();
        InitialCameraHeightAboveFloor = InitialCameraLocation.Z - InitialFloorImpactPoint.Z;
        InitialCapsuleBottomAboveFloor = InitialPlayerLocation.Z - InitialCapsuleHalfHeight - InitialFloorImpactPoint.Z;
        bGroundedInitially = Sample.bGrounded && bInitialFloorBlocking && bInitialFloorWalkable;
        ValidationViewRotation = PC->GetControlRotation();
        SendValidationMouse(PC, EKeys::MouseX, 60.f);
        SendValidationMouse(PC, EKeys::MouseY, 30.f);
        ValidationStage = 6; StageStarted = Now;
        ValidationStatus = TEXT("Validation: mouse yaw and pitch");
    }
    else if (ValidationStage == 6)
    {
        MouseYawChange = FMath::Max(MouseYawChange,
            FRotator::NormalizeAxis(PC->GetControlRotation().Yaw - ValidationViewRotation.Yaw));
        MousePitchChange = FMath::Max(MousePitchChange,
            FRotator::NormalizeAxis(PC->GetControlRotation().Pitch - ValidationViewRotation.Pitch));
        if (StageTime >= .4)
        {
            PC->SetIgnoreLookInput(true);
            bValidationLookLocked = true;
            PC->SetControlRotation(ValidationViewRotation);
            ValidationStage = 7; StageStarted = Now;
        }
    }
    else if (ValidationStage == 7 && StageTime >= .2)
    {
        MovementStart = Character->GetActorLocation();
        CaptureValidation(TEXT("idle"));
        SendValidationKey(PC, EKeys::W, IE_Pressed);
        ValidationStage = 1; StageStarted = Now;
        ValidationStatus = TEXT("Validation: W movement and ground collision");
    }
    else if (ValidationStage == 1 && StageTime >= 1.2)
    {
        SendValidationKey(PC, EKeys::W, IE_Released);
        MovementDistance = FVector::Dist2D(MovementStart, Character->GetActorLocation());
        JumpStart = Character->GetActorLocation();
        SendValidationKey(PC, EKeys::SpaceBar, IE_Pressed);
        ValidationStage = 2; StageStarted = Now;
        ValidationStatus = TEXT("Validation: Space jump");
    }
    else if (ValidationStage == 2)
    {
        MaximumJumpHeight = FMath::Max(MaximumJumpHeight, float(Character->GetActorLocation().Z - JumpStart.Z));
        if (!bJumpReleased && StageTime >= .12)
        {
            SendValidationKey(PC, EKeys::SpaceBar, IE_Released);
            bJumpReleased = true;
        }
        if (StageTime >= 1.3)
        {
            SendValidationKey(PC, EKeys::Q, IE_Pressed);
            ValidationStage = 3; StageStarted = Now;
            ValidationStatus = TEXT("Validation: Q one-shot and synchronized lights");
        }
    }
    else if (ValidationStage == 3)
    {
        if (StageTime > .035) SendValidationKey(PC, EKeys::Q, IE_Released);
        if (!bFlashCaptured && Effect->bExplosionActive && Effect->ElapsedSeconds >= .055f)
        {
            CaptureValidation(TEXT("flash"));
            bFlashCaptured = true;
        }
        if (!bFireCaptured && Effect->bExplosionActive && Effect->ElapsedSeconds >= .6f)
        {
            CaptureValidation(TEXT("fire"));
            bFireCaptured = true;
        }
        if (StageTime >= FMath::Max(Effect->PlaybackDuration + .5f, 2.f))
        {
            bOneShotStopped = !Effect->bExplosionActive && Effect->IsHidden() && LightsOff(Effect)
                && Effect->GaussianComponent->NormalizedTime >= .999f;
            CaptureValidation(TEXT("after"));
            SendValidationKey(PC, EKeys::Q, IE_Pressed);
            ValidationStage = 4; StageStarted = Now;
            ValidationStatus = TEXT("Validation: repeated Q restarts the active explosion");
        }
    }
    else if (ValidationStage == 4)
    {
        if (StageTime > .035) SendValidationKey(PC, EKeys::Q, IE_Released);
        if (StageTime >= .65)
        {
            SendValidationKey(PC, EKeys::Q, IE_Pressed);
            ValidationStage = 5; StageStarted = Now;
        }
    }
    else if (ValidationStage == 5)
    {
        if (StageTime > .035) SendValidationKey(PC, EKeys::Q, IE_Released);
        if (Effect->TriggerCount >= 3 && Effect->bExplosionActive && StageTime <= .4)
            bRetriggerRestarted = Effect->ElapsedSeconds < .4f && Effect->GaussianComponent->NormalizedTime < .3f;
        if (StageTime >= FMath::Max(Effect->PlaybackDuration + .5f, 2.f))
        {
            SaveValidation();
            bValidationFinished = true;
            StageStarted = Now;
        }
    }
}

void AGS4DTrenchGameMode::SaveValidation()
{
    APlayerController* PC = GetWorld()->GetFirstPlayerController();
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    const AGS4DTrenchExplosion* Effect = FindExplosion(GetWorld());
    const int32 SourceFrames = Effect && Effect->GaussianComponent->Sequence
        ? Effect->GaussianComponent->Sequence->FrameCount : 0;
    TArray<float> ActiveFrameSeconds;
    TArray<float> IdleFrameSeconds;
    TArray<float> FirstOneShotFrameSeconds;
    TSet<int32> FirstOneShotIndices;
    int32 FirstOneShotUniqueTimes = 0;
    TArray<float> UninterruptedOneShotFrameSeconds;
    TSet<int32> UninterruptedOneShotIndices;
    int32 UninterruptedOneShotUniqueTimes = 0;
    int32 UninterruptedSameFrameAlphaChanged = 0;
    int32 SameFrameTimeAdvanced = 0;
    int32 SameFrameAlphaChanged = 0;
    int32 ProjectionStateChanges = 0;
    int32 InterpolationCVar = -1;
    double ActiveSeconds = 0.0;
    float MinimumAlpha = 1.f;
    float MaximumAlpha = 0.f;
    float PreviousFirstOneShotTime = -1.f;
    float PreviousUninterruptedOneShotTime = -1.f;
    bool bLastSampleHeld = false;
    bool bUninterruptedLastSampleHeld = false;
    bool bNoEndToStartBlend = true;
    bool bValidProjectionStates = true;
    const FGS4DTrenchValidationSample* Previous = nullptr;
    for (const FGS4DTrenchValidationSample& Sample : ValidationSamples)
    {
        if (Sample.Stage == 0 && Sample.Time >= 8.0 && !Sample.bActive && Sample.DeltaSeconds > 0.f)
            IdleFrameSeconds.Add(Sample.DeltaSeconds);
        if (Sample.bActive && Sample.DeltaSeconds > 0.f)
        {
            ActiveFrameSeconds.Add(Sample.DeltaSeconds);
            ActiveSeconds += Sample.DeltaSeconds;
            InterpolationCVar = Sample.InterpolationCVar;
            MinimumAlpha = FMath::Min(MinimumAlpha, Sample.ProjectionAlpha);
            MaximumAlpha = FMath::Max(MaximumAlpha, Sample.ProjectionAlpha);
            bValidProjectionStates &= Sample.ProjectionFrameA >= 0 && Sample.ProjectionFrameA < SourceFrames
                && Sample.ProjectionFrameB >= Sample.ProjectionFrameA && Sample.ProjectionFrameB < SourceFrames
                && Sample.ProjectionAlpha >= 0.f && Sample.ProjectionAlpha <= 1.f;
            if (SourceFrames > 1 && Sample.ProjectionFrameA == SourceFrames - 1)
            {
                const bool bHeld = Sample.ProjectionFrameB == Sample.ProjectionFrameA && Sample.ProjectionAlpha == 0.f;
                bNoEndToStartBlend &= bHeld;
                if (Sample.TriggerCount == 1) bLastSampleHeld |= bHeld && Sample.NormalizedTime >= .999f;
                if (Sample.TriggerCount == 3) bUninterruptedLastSampleHeld |= bHeld && Sample.NormalizedTime >= .999f;
            }
            if (Sample.TriggerCount == 1)
            {
                FirstOneShotFrameSeconds.Add(Sample.DeltaSeconds);
                FirstOneShotIndices.Add(Sample.FrameIndex);
                if (Sample.NormalizedTime != PreviousFirstOneShotTime) ++FirstOneShotUniqueTimes;
                PreviousFirstOneShotTime = Sample.NormalizedTime;
            }
            if (Sample.TriggerCount == 3)
            {
                // The third Q playback completes without synchronous validation screenshots.
                UninterruptedOneShotFrameSeconds.Add(Sample.DeltaSeconds);
                UninterruptedOneShotIndices.Add(Sample.FrameIndex);
                if (Sample.NormalizedTime != PreviousUninterruptedOneShotTime) ++UninterruptedOneShotUniqueTimes;
                PreviousUninterruptedOneShotTime = Sample.NormalizedTime;
            }
            if (Previous && Previous->bActive && Previous->TriggerCount == Sample.TriggerCount)
            {
                const bool bTimeAdvanced = Sample.NormalizedTime > Previous->NormalizedTime;
                const bool bSameFrame = Sample.FrameIndex == Previous->FrameIndex;
                const bool bAlphaChanged = Sample.ProjectionAlpha != Previous->ProjectionAlpha;
                if (bTimeAdvanced && bSameFrame) ++SameFrameTimeAdvanced;
                if (bTimeAdvanced && bSameFrame && bAlphaChanged && Sample.InterpolationCVar > 0) ++SameFrameAlphaChanged;
                if (Sample.TriggerCount == 3 && bTimeAdvanced && bSameFrame && bAlphaChanged && Sample.InterpolationCVar > 0)
                    ++UninterruptedSameFrameAlphaChanged;
                if (Sample.InterpolationCVar > 0 && (bAlphaChanged
                    || Sample.ProjectionFrameA != Previous->ProjectionFrameA || Sample.ProjectionFrameB != Previous->ProjectionFrameB))
                    ++ProjectionStateChanges;
            }
        }
        Previous = &Sample;
    }
    const TSharedRef<FJsonObject> ActiveTiming = FrameTimingJson(ActiveFrameSeconds);
    const TSharedRef<FJsonObject> FirstOneShotTiming = FrameTimingJson(FirstOneShotFrameSeconds);
    const TSharedRef<FJsonObject> UninterruptedOneShotTiming = FrameTimingJson(UninterruptedOneShotFrameSeconds);
    const bool bContinuityCheckApplicable = InterpolationCVar > 0 && SourceFrames > 1
        && UninterruptedOneShotTiming->GetNumberField(TEXT("mean_fps")) > 60.0;
    const bool bContinuousProjectionVerified = InterpolationCVar > 0 && bValidProjectionStates && bNoEndToStartBlend
        && bUninterruptedLastSampleHeld && UninterruptedOneShotIndices.Num() == SourceFrames
        && UninterruptedOneShotUniqueTimes > SourceFrames && UninterruptedSameFrameAlphaChanged > 0;
    const bool bPlayerDimensionsScaled = bInitialSceneStateRecorded && InitialCharacterScale > 0.f
        && FMath::IsNearlyEqual(InitialCapsuleRadius, 34.f * InitialCharacterScale, .05f)
        && FMath::IsNearlyEqual(InitialCapsuleHalfHeight, 88.f * InitialCharacterScale, .05f)
        && InitialCameraRelativeLocation.Equals(FVector(0.f, 0.f, 68.f * InitialCharacterScale), .05f);
    const bool bPassed = Effect && bIdleOff && bGroundedInitially && MovementDistance > 10.f
        && bPlayerDimensionsScaled
        && (!bContinuityCheckApplicable || bContinuousProjectionVerified)
        && MouseYawChange > 3.f && MousePitchChange > 1.5f
        && MaximumJumpHeight > 20.f && MaximumFlashIntensity > 0.f && MaximumFireIntensity > 0.f
        && bOneShotStopped && bRetriggerRestarted && bFlashCaptured && bFireCaptured
        && Effect->TriggerCount >= 3 && !Effect->bExplosionActive && LightsOff(Effect);
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("map"), GetWorld()->GetMapName());
    Root->SetStringField(TEXT("created_utc"), FDateTime::UtcNow().ToIso8601());
    Root->SetBoolField(TEXT("passed"), bPassed);
    const TSharedRef<FJsonObject> Performance = MakeShared<FJsonObject>();
    Performance->SetObjectField(TEXT("active_playback"), ActiveTiming);
    Performance->SetObjectField(TEXT("settled_idle"), FrameTimingJson(IdleFrameSeconds));
    Performance->SetObjectField(TEXT("first_one_shot"), FirstOneShotTiming);
    Performance->SetObjectField(TEXT("uninterrupted_one_shot"), UninterruptedOneShotTiming);
    Performance->SetStringField(TEXT("measurement"), TEXT("Game-thread DeltaSeconds; mean FPS is frame count divided by summed frame time. Idle uses stationary seconds 8-10 after warmup. First one-shot and aggregate active timing include synchronous screenshot overhead, which may skip source samples. Uninterrupted one-shot uses the third Q playback, with no screenshots. These are not GPU timings."));
    Root->SetObjectField(TEXT("runtime_performance"), Performance);
    const TSharedRef<FJsonObject> Continuity = MakeShared<FJsonObject>();
    Continuity->SetNumberField(TEXT("interpolation_cvar"), InterpolationCVar);
    Continuity->SetBoolField(TEXT("interpolation_enabled"), InterpolationCVar > 0);
    Continuity->SetNumberField(TEXT("source_sample_count"), SourceFrames);
    Continuity->SetNumberField(TEXT("first_one_shot_sample_indices_seen"), FirstOneShotIndices.Num());
    Continuity->SetNumberField(TEXT("first_one_shot_unique_normalized_times"), FirstOneShotUniqueTimes);
    Continuity->SetNumberField(TEXT("uninterrupted_one_shot_trigger_count"), 3);
    Continuity->SetNumberField(TEXT("uninterrupted_one_shot_sample_indices_seen"), UninterruptedOneShotIndices.Num());
    Continuity->SetNumberField(TEXT("uninterrupted_one_shot_unique_normalized_times"), UninterruptedOneShotUniqueTimes);
    Continuity->SetNumberField(TEXT("uninterrupted_one_shot_same_frame_alpha_changed"), UninterruptedSameFrameAlphaChanged);
    Continuity->SetBoolField(TEXT("uninterrupted_one_shot_final_sample_held"), bUninterruptedLastSampleHeld);
    Continuity->SetNumberField(TEXT("same_frame_time_advanced"), SameFrameTimeAdvanced);
    Continuity->SetNumberField(TEXT("same_frame_alpha_changed"), SameFrameAlphaChanged);
    Continuity->SetNumberField(TEXT("projection_state_changes"), ProjectionStateChanges);
    Continuity->SetNumberField(TEXT("active_fractional_state_changes_per_second"), ActiveSeconds > 0.0 ? ProjectionStateChanges / ActiveSeconds : 0.0);
    Continuity->SetNumberField(TEXT("minimum_requested_frame_alpha"), ActiveFrameSeconds.IsEmpty() ? 0.f : MinimumAlpha);
    Continuity->SetNumberField(TEXT("maximum_requested_frame_alpha"), MaximumAlpha);
    Continuity->SetBoolField(TEXT("valid_projection_frame_pairs_and_alpha"), bValidProjectionStates);
    Continuity->SetBoolField(TEXT("no_end_to_start_interpolation"), bNoEndToStartBlend);
    Continuity->SetBoolField(TEXT("first_one_shot_final_sample_held"), bLastSampleHeld);
    Continuity->SetBoolField(TEXT("continuity_check_applicable_over_60_fps"), bContinuityCheckApplicable);
    Continuity->SetBoolField(TEXT("continuous_projection_verified"), bContinuousProjectionVerified);
    Continuity->SetStringField(TEXT("evidence_scope"), TEXT("GetInterpolationState shares frame-selection math with the render path. Values are requested game-thread projection state, not GPU readback or captured-image motion analysis. Above 60 FPS, validation uses the third Q playback without screenshots: all source samples, more distinct times than source samples, fractional alpha changes within a held source frame, and a held final sample without blending to the beginning. First playback coverage remains diagnostic because synchronous screenshot saving can stall longer than a source-sample interval."));
    Root->SetObjectField(TEXT("playback_continuity"), Continuity);
    Root->SetStringField(TEXT("controller_class"), PC ? PC->GetClass()->GetPathName() : TEXT("<none>"));
    Root->SetStringField(TEXT("pawn_class"), Pawn ? Pawn->GetClass()->GetPathName() : TEXT("<none>"));
    FString FailureReason;
    if (!PC) FailureReason += TEXT("No local player controller. ");
    else if (!Pawn) FailureReason += TEXT("Player controller has no possessed pawn. ") + LastSpawnDiagnosis + TEXT(". ");
    else if (!Pawn->IsA<AGS4DTrenchCharacter>()) FailureReason += TEXT("Possessed pawn is not a GS4DTrenchCharacter. ");
    if (!Effect) FailureReason += TEXT("No GS4DTrenchExplosion actor in the world. ");
    if (!bPassed && FailureReason.IsEmpty()) FailureReason = TEXT("One or more gameplay checks failed; inspect the individual check fields and samples");
    Root->SetStringField(TEXT("failure_reason"), FailureReason);
    const TSharedRef<FJsonObject> Spawn = MakeShared<FJsonObject>();
    Spawn->SetBoolField(TEXT("attempted"), bSpawnAttempted);
    Spawn->SetBoolField(TEXT("succeeded"), bLastSpawnSucceeded);
    Spawn->SetStringField(TEXT("pawn_class"), LastSpawnPawnClass);
    Spawn->SetArrayField(TEXT("requested_location_cm"), VectorJson(LastSpawnLocation));
    Spawn->SetArrayField(TEXT("result_location_cm"), VectorJson(LastSpawnActualLocation));
    Spawn->SetStringField(TEXT("requested_rotation"), LastSpawnRotation.ToString());
    Spawn->SetStringField(TEXT("diagnosis"), LastSpawnDiagnosis);
    TArray<TSharedPtr<FJsonValue>> Blockers;
    for (const FString& Blocker : LastSpawnBlockers) Blockers.Add(MakeShared<FJsonValueString>(Blocker));
    Spawn->SetArrayField(TEXT("blocking_actor_and_component_paths"), Blockers);
    Root->SetObjectField(TEXT("last_default_pawn_spawn"), Spawn);
    Root->SetNumberField(TEXT("visual_fog_exact_component_matches"), VisualFogMatchedCount);
    Root->SetNumberField(TEXT("visual_fog_Pawn_response_fixes"), VisualFogCollisionFixCount);
    TArray<TSharedPtr<FJsonValue>> FogComponents;
    for (const FString& Path : VisualFogComponentPaths) FogComponents.Add(MakeShared<FJsonValueString>(Path));
    Root->SetArrayField(TEXT("visual_fog_component_paths"), FogComponents);
    Root->SetBoolField(TEXT("idle_hidden_and_lights_off"), bIdleOff);
    Root->SetBoolField(TEXT("initially_grounded_with_floor_collision"), bGroundedInitially);
    Root->SetBoolField(TEXT("player_dimensions_match_character_scale"), bPlayerDimensionsScaled);
    const TSharedRef<FJsonObject> InitialState = MakeShared<FJsonObject>();
    InitialState->SetBoolField(TEXT("recorded_after_warmup"), bInitialSceneStateRecorded);
    InitialState->SetArrayField(TEXT("player_location_cm"), VectorJson(InitialPlayerLocation));
    InitialState->SetNumberField(TEXT("character_scale"), InitialCharacterScale);
    InitialState->SetNumberField(TEXT("capsule_radius_cm"), InitialCapsuleRadius);
    InitialState->SetNumberField(TEXT("capsule_half_height_cm"), InitialCapsuleHalfHeight);
    InitialState->SetNumberField(TEXT("capsule_height_cm"), InitialCapsuleHalfHeight * 2.f);
    InitialState->SetArrayField(TEXT("camera_relative_location_cm"), VectorJson(InitialCameraRelativeLocation));
    InitialState->SetNumberField(TEXT("camera_height_above_movement_floor_cm"), InitialCameraHeightAboveFloor);
    InitialState->SetNumberField(TEXT("capsule_bottom_above_movement_floor_cm"), InitialCapsuleBottomAboveFloor);
    InitialState->SetArrayField(TEXT("camera_location_cm"), VectorJson(InitialCameraLocation));
    InitialState->SetStringField(TEXT("camera_rotation"), InitialCameraRotation.ToString());
    InitialState->SetBoolField(TEXT("movement_floor_blocking_hit"), bInitialFloorBlocking);
    InitialState->SetBoolField(TEXT("movement_floor_walkable"), bInitialFloorWalkable);
    InitialState->SetStringField(TEXT("movement_floor_actor_path"), InitialFloorActorPath);
    InitialState->SetStringField(TEXT("movement_floor_component_path"), InitialFloorComponentPath);
    InitialState->SetArrayField(TEXT("movement_floor_impact_point_cm"), VectorJson(InitialFloorImpactPoint));
    InitialState->SetNumberField(TEXT("movement_floor_distance_cm"), InitialFloorDistance);
    InitialState->SetStringField(TEXT("floor_source"), TEXT("UCharacterMovementComponent::CurrentFloor (Pawn collision), not the supplemental Visibility trace"));
    Root->SetObjectField(TEXT("initial_scene_state"), InitialState);
    Root->SetNumberField(TEXT("input_W_distance_cm"), MovementDistance);
    Root->SetNumberField(TEXT("input_Space_jump_height_cm"), MaximumJumpHeight);
    Root->SetNumberField(TEXT("input_MouseX_positive_yaw_degrees"), MouseYawChange);
    Root->SetNumberField(TEXT("input_MouseY_positive_up_pitch_degrees"), MousePitchChange);
    Root->SetBoolField(TEXT("input_Q_one_shot_stopped_hidden_lights_off"), bOneShotStopped);
    Root->SetBoolField(TEXT("input_Q_retrigger_restarted_clock"), bRetriggerRestarted);
    Root->SetNumberField(TEXT("flash_max_lumens"), MaximumFlashIntensity);
    Root->SetNumberField(TEXT("fire_max_lumens"), MaximumFireIntensity);
    Root->SetNumberField(TEXT("trigger_count"), Effect ? Effect->TriggerCount : 0);
    Root->SetNumberField(TEXT("playback_duration_seconds"), Effect ? Effect->PlaybackDuration : 0.f);
    const UMaterialInterface* EffectiveMaterial = Effect ? Effect->GaussianComponent->GetMaterial(0) : nullptr;
    const UMaterialInterface* SequenceMaterial = Effect && Effect->GaussianComponent->Sequence
        ? Effect->GaussianComponent->Sequence->SplatMaterial.Get() : nullptr;
    Root->SetStringField(TEXT("effective_component_material_path"), GetPathNameSafe(EffectiveMaterial));
    Root->SetStringField(TEXT("sequence_material_path"), GetPathNameSafe(SequenceMaterial));
    Root->SetBoolField(TEXT("component_uses_sequence_material"), EffectiveMaterial && EffectiveMaterial == SequenceMaterial);
    Root->SetArrayField(TEXT("effect_actor_location_cm"), VectorJson(Effect ? Effect->GetActorLocation() : FVector::ZeroVector));
    Root->SetArrayField(TEXT("effect_actor_scale"), VectorJson(Effect ? Effect->GetActorScale3D() : FVector::ZeroVector));
    Root->SetStringField(TEXT("effect_actor_rotation"), Effect ? Effect->GetActorRotation().ToString() : TEXT("<none>"));
    Root->SetStringField(TEXT("input_method"), TEXT("APlayerController::InputKey: W, SpaceBar, Q and raw MouseX/MouseY events"));
    if (Effect && Effect->GaussianComponent->Sequence)
    {
        Root->SetNumberField(TEXT("sequence_points"), Effect->GaussianComponent->Sequence->PointCount);
        Root->SetNumberField(TEXT("sequence_frames"), Effect->GaussianComponent->Sequence->FrameCount);
        Root->SetNumberField(TEXT("sequence_sampled_span_seconds"), Effect->GaussianComponent->Sequence->DurationSeconds);
    }
    TArray<TSharedPtr<FJsonValue>> ScreenshotValues;
    for (const FString& Path : ValidationScreenshots) ScreenshotValues.Add(MakeShared<FJsonValueString>(Path));
    Root->SetArrayField(TEXT("screenshots"), ScreenshotValues);
    TArray<TSharedPtr<FJsonValue>> Samples;
    for (const FGS4DTrenchValidationSample& Sample : ValidationSamples)
    {
        const TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
        Item->SetNumberField(TEXT("time"), Sample.Time);
        Item->SetNumberField(TEXT("frame_ms"), Sample.DeltaSeconds * 1000.f);
        Item->SetArrayField(TEXT("player_location_cm"), VectorJson(Sample.Location));
        Item->SetArrayField(TEXT("player_velocity_cm_s"), VectorJson(Sample.Velocity));
        Item->SetBoolField(TEXT("grounded"), Sample.bGrounded);
        Item->SetBoolField(TEXT("floor_trace_hit"), Sample.bGroundTrace);
        Item->SetBoolField(TEXT("explosion_active"), Sample.bActive);
        Item->SetBoolField(TEXT("explosion_hidden"), Sample.bHidden);
        Item->SetNumberField(TEXT("normalized_time"), Sample.NormalizedTime);
        Item->SetNumberField(TEXT("sequence_frame_zero_based"), Sample.FrameIndex);
        Item->SetNumberField(TEXT("requested_projection_frame_a"), Sample.ProjectionFrameA);
        Item->SetNumberField(TEXT("requested_projection_frame_b"), Sample.ProjectionFrameB);
        Item->SetNumberField(TEXT("requested_projection_alpha"), Sample.ProjectionAlpha);
        Item->SetNumberField(TEXT("interpolation_cvar"), Sample.InterpolationCVar);
        Item->SetNumberField(TEXT("validation_stage"), Sample.Stage);
        Item->SetNumberField(TEXT("flash_lumens"), Sample.FlashIntensity);
        Item->SetNumberField(TEXT("fire_lumens"), Sample.FireIntensity);
        Item->SetNumberField(TEXT("trigger_count"), Sample.TriggerCount);
        Samples.Add(MakeShared<FJsonValueObject>(Item));
    }
    Root->SetArrayField(TEXT("samples"), Samples);
    FString Json;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
    FJsonSerializer::Serialize(Root, Writer);
    const FString ReportPath = FPaths::Combine(ValidationFolder, TEXT("report.json"));
    const FString LatestPath = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("GS4DTrenchValidation"), TEXT("latest-trench-validation.json"));
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(LatestPath), true);
    const bool bSaved = FFileHelper::SaveStringToFile(Json, *ReportPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)
        && FFileHelper::SaveStringToFile(Json, *LatestPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    ValidationStatus = bPassed && bSaved ? TEXT("Validation PASSED") : TEXT("Validation FAILED - see saved report");
    UE_LOG(LogGS4DTrench, Display, TEXT("%s: %s"), *ValidationStatus, *ReportPath);
    if (PC && bValidationLookLocked)
    {
        PC->SetIgnoreLookInput(false);
        bValidationLookLocked = false;
    }
}
