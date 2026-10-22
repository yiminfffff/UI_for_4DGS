#include "GS4DPreview.h"
#include "GS4DComponent.h"
#include "Camera/CameraComponent.h"
#include "Components/InputComponent.h"
#include "Components/SphereComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/FloatingPawnMovement.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMemory.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "RenderTimer.h"
#include "RHI.h"
#include "DynamicRHI.h"
#include "Serialization/JsonSerializer.h"
#include "Dom/JsonObject.h"
#include "UnrealClient.h"
#include "TimerManager.h"

namespace
{
const TCHAR* PhaseNames[] = {TEXT("Static"), TEXT("Playback"), TEXT("Moving"), TEXT("CloseUp"), TEXT("Hidden")};

FBox EffectBounds(UWorld* World)
{
    FBox Result(ForceInit);
    for (TActorIterator<AGS4DActor> It(World); It; ++It)
        Result += It->GaussianComponent->Bounds.GetBox();
    return Result.IsValid ? Result : FBox(FVector(-100), FVector(100));
}

void SetPlayback(UWorld* World, bool Playing, bool Hidden = false)
{
    for (TActorIterator<AGS4DActor> It(World); It; ++It)
    {
        It->SetActorHiddenInGame(Hidden);
        It->GaussianComponent->bLoop = true;
        It->GaussianComponent->bPlaying = Playing;
        if (!Playing) It->GaussianComponent->SetNormalizedTime(0.5f);
    }
}

void SendKey(APlayerController* PC, FKey Key, EInputEvent Event, float Amount)
{
    PC->InputKey(FInputKeyEventArgs(nullptr, FInputDeviceId::CreateFromInternalId(0),
        Key, Event, Amount, false, FPlatformTime::Cycles64()));
}
}

AGS4DPreviewPawn::AGS4DPreviewPawn()
{
    bAddDefaultMovementBindings = false;
    GetMeshComponent()->SetVisibility(false);
    GetCollisionComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    auto* Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("PreviewCamera"));
    Camera->SetupAttachment(RootComponent);
    Camera->bUsePawnControlRotation = true;
    Camera->bLockToHmd = false;
    Camera->FieldOfView = 60;
    if (auto* Movement = Cast<UFloatingPawnMovement>(GetMovementComponent()))
    {
        Movement->MaxSpeed = 300;
        Movement->Acceleration = 1800;
        Movement->Deceleration = 2400;
    }
}

void AGS4DPreviewPawn::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    auto* PC = Cast<APlayerController>(Controller);
    if (!PC || PC->bShowMouseCursor) return;
    const FRotator Rotation = PC->GetControlRotation();
    FVector Direction = Rotation.Vector() * (float(PC->IsInputKeyDown(EKeys::W)) - float(PC->IsInputKeyDown(EKeys::S)));
    Direction += FRotationMatrix(Rotation).GetUnitAxis(EAxis::Y) *
        (float(PC->IsInputKeyDown(EKeys::D)) - float(PC->IsInputKeyDown(EKeys::A)));
    Direction += FVector::UpVector * (float(PC->IsInputKeyDown(EKeys::E)) - float(PC->IsInputKeyDown(EKeys::Q)));
    if (auto* Movement = Cast<UFloatingPawnMovement>(GetMovementComponent()))
        Movement->MaxSpeed = PC->IsInputKeyDown(EKeys::LeftShift) ? 1200 : 300;
    AddMovementInput(Direction.GetSafeNormal());
}

void AGS4DPreviewPawn::SetupPlayerInputComponent(UInputComponent* Input)
{
    Super::SetupPlayerInputComponent(Input);
    Input->BindAxisKey(EKeys::MouseX, this, &AGS4DPreviewPawn::LookHorizontal);
    Input->BindAxisKey(EKeys::MouseY, this, &AGS4DPreviewPawn::LookVertical);
    Input->BindKey(EKeys::SpaceBar, IE_Pressed, this, &AGS4DPreviewPawn::TogglePlayback);
    Input->BindKey(EKeys::R, IE_Pressed, this, &AGS4DPreviewPawn::RestartPlayback);
    Input->BindKey(EKeys::F, IE_Pressed, this, &AGS4DPreviewPawn::FocusEffect);
    Input->BindKey(EKeys::F1, IE_Pressed, this, &AGS4DPreviewPawn::ToggleCursor);
    Input->BindKey(EKeys::Tab, IE_Pressed, this, &AGS4DPreviewPawn::ToggleStats);
    Input->BindKey(EKeys::F8, IE_Pressed, this, &AGS4DPreviewPawn::Benchmark);
    Input->BindKey(EKeys::Escape, IE_Pressed, this, &AGS4DPreviewPawn::ExitPreview);
}

void AGS4DPreviewPawn::LookHorizontal(float Value)
{
    auto* PC = Cast<APlayerController>(Controller);
    if (PC && !PC->bShowMouseCursor) AddControllerYawInput(Value * 0.2f);
}
void AGS4DPreviewPawn::LookVertical(float Value)
{
    auto* PC = Cast<APlayerController>(Controller);
    if (PC && !PC->bShowMouseCursor) AddControllerPitchInput(-Value * 0.2f);
}

void AGS4DPreviewPawn::FocusEffect()
{
    const FBox Box = EffectBounds(GetWorld());
    const FVector Target = Box.GetCenter();
    const float Distance = FMath::Max(float(Box.GetExtent().GetMax() * 3.2), 200.f);
    const FVector Location = Target + FVector(-Distance, -Distance * 0.35, Distance * 0.3);
    SetActorLocation(Location);
    if (Controller) Controller->SetControlRotation((Target - Location).Rotation());
    if (GetMovementComponent()) GetMovementComponent()->StopMovementImmediately();
}

void AGS4DPreviewPawn::TogglePlayback()
{
    bool Playing = false;
    for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        Playing |= It->GaussianComponent->bPlaying;
    for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        It->GaussianComponent->bPlaying = !Playing;
}
void AGS4DPreviewPawn::RestartPlayback()
{
    for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
    {
        It->GaussianComponent->SetNormalizedTime(0);
        It->GaussianComponent->Play();
    }
}
void AGS4DPreviewPawn::ToggleCursor()
{
    if (auto* PC = Cast<APlayerController>(Controller))
    {
        PC->bShowMouseCursor = !PC->bShowMouseCursor;
        if (PC->bShowMouseCursor) PC->SetInputMode(FInputModeGameAndUI());
        else PC->SetInputMode(FInputModeGameOnly());
    }
}
void AGS4DPreviewPawn::ToggleStats()
{
    if (auto* PC = Cast<APlayerController>(Controller))
        if (auto* HUD = Cast<AGS4DPreviewHUD>(PC->GetHUD())) HUD->bShowStats = !HUD->bShowStats;
}
void AGS4DPreviewPawn::Benchmark()
{
    if (auto* Mode = GetWorld()->GetAuthGameMode<AGS4DPreviewGameMode>()) Mode->StartBenchmark();
}
void AGS4DPreviewPawn::ExitPreview()
{
    if (GetWorld()->WorldType != EWorldType::PIE) FPlatformMisc::RequestExit(false);
}

void AGS4DPreviewController::BeginPlay()
{
    Super::BeginPlay();
    bShowMouseCursor = false;
    SetInputMode(FInputModeGameOnly());
    GetWorldTimerManager().SetTimerForNextTick([this]()
    {
        if (auto* Pawn = Cast<AGS4DPreviewPawn>(GetPawn())) Pawn->FocusEffect();
    });
}

void AGS4DPreviewHUD::DrawHUD()
{
    Super::DrawHUD();
    if (!Canvas || !bShowStats) return;
    const float FrameMS = GetWorld()->GetDeltaSeconds() * 1000;
    SmoothedFrameMS = SmoothedFrameMS > 0 ? FMath::Lerp(SmoothedFrameMS, FrameMS, 0.08f) : FrameMS;
    int32 Points = 0, Frames = 0, Frame = 0;
    double DataMB = 0;
    bool Playing = false;
    for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
    {
        UGS4DComponent* C = It->GaussianComponent.Get();
        if (!C->Sequence) continue;
        Points += C->Sequence->PointCount; Frames = C->Sequence->FrameCount;
        Frame = C->FrameIndex() + 1; Playing |= C->bPlaying;
        DataMB += C->Sequence->FrameData.Num() / 1048576.0;
    }
    DrawRect(FLinearColor(0.01f, 0.02f, 0.03f, 0.85f), 14, 14, 670, 126);
    DrawText(TEXT("4DGS REALTIME PREVIEW"), FLinearColor(0.3f, 1.f, 0.8f), 26, 22);
    DrawText(FString::Printf(TEXT("%.1f FPS | %.2f ms | Game %.2f | Render %.2f | GPU %.2f ms"),
        1000.f/FMath::Max(SmoothedFrameMS, .001f), SmoothedFrameMS,
        FPlatformTime::ToMilliseconds(GGameThreadTime), FPlatformTime::ToMilliseconds(GRenderThreadTime),
        FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles())), FLinearColor::White, 26, 43);
    DrawText(FString::Printf(TEXT("%s | Frame %d / %d | %d points | Animation data %.1f MB"),
        Playing ? TEXT("Playing") : TEXT("Paused"), Frame, Frames, Points, DataMB), FLinearColor::White, 26, 63);
    DrawText(TEXT("WASD: Move | Mouse: Look | Q/E: Down/Up | Shift: Fast | F: Focus"), FLinearColor::White, 26, 83);
    DrawText(TEXT("Space: Play/Pause | R: Restart | F1: Cursor | Tab: Stats | F8: Benchmark | Esc: Exit"),
        FLinearColor::White, 26, 103);
    if (auto* Mode = GetWorld()->GetAuthGameMode<AGS4DPreviewGameMode>())
        if (!Mode->BenchmarkStatus.IsEmpty()) DrawText(Mode->BenchmarkStatus, FLinearColor::Yellow, 26, 151);
}

AGS4DPreviewGameMode::AGS4DPreviewGameMode()
{
    DefaultPawnClass = AGS4DPreviewPawn::StaticClass();
    PlayerControllerClass = AGS4DPreviewController::StaticClass();
    HUDClass = AGS4DPreviewHUD::StaticClass();
    PrimaryActorTick.bCanEverTick = true;
}
void AGS4DPreviewGameMode::BeginPlay()
{
    Super::BeginPlay();
    SetPlayback(GetWorld(), true);
    if (FParse::Param(FCommandLine::Get(), TEXT("GS4DBenchmark"))) StartBenchmark();
}
void AGS4DPreviewGameMode::StartBenchmark()
{
    if (bBenchmarking) return;
    bBenchmarking = true; Phase = -1; InputStep = 0;
    Started = PreviousTick = FPlatformTime::Seconds();
    ForwardDistance = RightDistance = 0; YawChange = 0;
    bSpacePauses = bRestartWorks = false;
    Samples.Empty(); Samples.SetNum(5);
    OutputFolder = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir() / TEXT("GS4DPreview") /
        (TEXT("Benchmark-") + FDateTime::Now().ToString(TEXT("%Y%m%d-%H%M%S"))));
    IFileManager::Get().MakeDirectory(*OutputFolder, true);
    BenchmarkStatus = TEXT("Benchmark warming up; input checks and shader warmup...");
}
void AGS4DPreviewGameMode::SetPhase(int32 Index)
{
    Phase = Index; PhaseStarted = FPlatformTime::Seconds(); bScreenshotTaken = false;
    SetPlayback(GetWorld(), Phase == 1 || Phase == 2 || Phase == 3, Phase == 4);
    if (auto* PC = GetWorld()->GetFirstPlayerController())
        if (auto* Pawn = Cast<AGS4DPreviewPawn>(PC->GetPawn())) Pawn->FocusEffect();
    if (Phase == 3)
        if (auto* PC = GetWorld()->GetFirstPlayerController())
            if (APawn* Pawn = PC->GetPawn())
            {
                const FVector Target = EffectBounds(GetWorld()).GetCenter();
                Pawn->SetActorLocation(Target + (Pawn->GetActorLocation() - Target) * 0.35);
            }
    BenchmarkStatus = FString::Printf(TEXT("Benchmark %s: 4 s warmup + 12 s measurement"), PhaseNames[Phase]);
}
void AGS4DPreviewGameMode::InputSmokeTest(double Elapsed)
{
    auto* PC = GetWorld()->GetFirstPlayerController();
    if (!PC || !PC->GetPawn()) return;
    if (InputStep == 0 && Elapsed > 1)
    { InputStart = PC->GetPawn()->GetActorLocation(); SendKey(PC, EKeys::W, IE_Pressed, 1); ++InputStep; }
    else if (InputStep == 1 && Elapsed > 1.4)
    {
        SendKey(PC, EKeys::W, IE_Released, 0);
        ForwardDistance = FVector::Distance(InputStart, PC->GetPawn()->GetActorLocation()); ++InputStep;
    }
    else if (InputStep == 2 && Elapsed > 1.8)
    { InputStart = PC->GetPawn()->GetActorLocation(); SendKey(PC, EKeys::D, IE_Pressed, 1); ++InputStep; }
    else if (InputStep == 3 && Elapsed > 2.2)
    {
        SendKey(PC, EKeys::D, IE_Released, 0);
        RightDistance = FVector::Distance(InputStart, PC->GetPawn()->GetActorLocation());
        InitialYaw = PC->GetControlRotation().Yaw;
        SendKey(PC, EKeys::MouseX, IE_Axis, 30); ++InputStep;
    }
    else if (InputStep == 4 && Elapsed > 2.6)
    { YawChange = FMath::Abs(FMath::FindDeltaAngleDegrees(InitialYaw, PC->GetControlRotation().Yaw)); ++InputStep; }
    else if (InputStep == 5 && Elapsed > 3)
    { SendKey(PC, EKeys::SpaceBar, IE_Pressed, 1); ++InputStep; }
    else if (InputStep == 6 && Elapsed > 3.2)
    {
        SendKey(PC, EKeys::SpaceBar, IE_Released, 0);
        for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        { bSpacePauses = !It->GaussianComponent->bPlaying; break; }
        ++InputStep;
    }
    else if (InputStep == 7 && Elapsed > 3.4)
    { SendKey(PC, EKeys::R, IE_Pressed, 1); ++InputStep; }
    else if (InputStep == 8 && Elapsed > 3.6)
    {
        SendKey(PC, EKeys::R, IE_Released, 0);
        for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        { bRestartWorks = It->GaussianComponent->bPlaying && It->GaussianComponent->NormalizedTime < 0.5; break; }
        ++InputStep;
    }
}
void AGS4DPreviewGameMode::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    if (!bBenchmarking) return;
    const double Now = FPlatformTime::Seconds();
    const double WallMS = (Now - PreviousTick) * 1000; PreviousTick = Now;
    if (Phase < 0)
    {
        InputSmokeTest(Now - Started);
        if (Now - Started > 10) SetPhase(0);
        return;
    }
    const double Elapsed = Now - PhaseStarted;
    if (Phase == 2)
    {
        if (auto* PC = GetWorld()->GetFirstPlayerController())
            if (APawn* Pawn = PC->GetPawn())
            {
                const FBox Box = EffectBounds(GetWorld());
                const FVector Target = Box.GetCenter();
                const double Radius = FMath::Max(Box.GetExtent().GetMax() * 3.4, 200.0);
                const FVector Location = Target + FVector(-FMath::Cos(Elapsed*0.3)*Radius,
                    FMath::Sin(Elapsed*0.3)*Radius, Radius*0.3);
                Pawn->SetActorLocation(Location);
                PC->SetControlRotation((Target-Location).Rotation());
            }
    }
    if (Elapsed < 3) return;
    if (!bScreenshotTaken)
    {
        FScreenshotRequest::RequestScreenshot(OutputFolder / (FString(PhaseNames[Phase]) + TEXT(".png")), true, false);
        bScreenshotTaken = true;
        return;
    }
    // Do not include screenshot readback in the performance sample window.
    if (Elapsed < 4) return;
    if (Elapsed < 16)
    {
        FGS4DPreviewSample S;
        S.FrameMS = WallMS;
        S.GameMS = FPlatformTime::ToMilliseconds(GGameThreadTime);
        S.RenderMS = FPlatformTime::ToMilliseconds(GRenderThreadTime);
        S.RHIMS = FPlatformTime::ToMilliseconds(GRHIThreadTime);
        S.GPUMS = FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles());
        S.MemoryMB = FPlatformMemory::GetStats().UsedPhysical / 1048576.0;
        for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        { S.Time = It->GaussianComponent->NormalizedTime; S.AnimationFrame = It->GaussianComponent->FrameIndex(); break; }
        Samples[Phase].Add(S);
        return;
    }
    if (Phase < 4) SetPhase(Phase + 1);
    else
    {
        SaveBenchmark(); bBenchmarking = false;
        SetPlayback(GetWorld(), true);
        if (auto* PC = GetWorld()->GetFirstPlayerController())
            if (auto* Pawn = Cast<AGS4DPreviewPawn>(PC->GetPawn())) Pawn->FocusEffect();
        BenchmarkStatus = TEXT("Benchmark complete: Saved/GS4DPreview");
        if (FParse::Param(FCommandLine::Get(), TEXT("GS4DBenchmarkExit"))) FPlatformMisc::RequestExit(false);
    }
}
void AGS4DPreviewGameMode::SaveBenchmark()
{
    auto Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("engine"), FEngineVersion::Current().ToString());
    Root->SetStringField(TEXT("gpu"), GRHIAdapterName);
    Root->SetStringField(TEXT("mode"), TEXT("Desktop standalone Development; asset stays resident in Hidden baseline"));
    Root->SetStringField(TEXT("output"), OutputFolder);
    for (TActorIterator<AGS4DActor> It(GetWorld()); It; ++It)
        if (auto* Asset = It->GaussianComponent->Sequence.Get())
        {
            Root->SetNumberField(TEXT("points"), Asset->PointCount);
            Root->SetNumberField(TEXT("animation_frames"), Asset->FrameCount);
            Root->SetNumberField(TEXT("duration_seconds"), Asset->DurationSeconds);
            Root->SetNumberField(TEXT("animation_data_mb"), Asset->FrameData.Num() / 1048576.0);
            break;
        }
    if (GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport)
    {
        const FIntPoint Size = GEngine->GameViewport->Viewport->GetSizeXY();
        Root->SetNumberField(TEXT("width"), Size.X); Root->SetNumberField(TEXT("height"), Size.Y);
    }
    auto Input = MakeShared<FJsonObject>();
    Input->SetNumberField(TEXT("w_distance_cm"), ForwardDistance);
    Input->SetNumberField(TEXT("d_distance_cm"), RightDistance);
    Input->SetNumberField(TEXT("mouse_yaw_degrees"), YawChange);
    Input->SetBoolField(TEXT("space_pauses"), bSpacePauses);
    Input->SetBoolField(TEXT("r_restarts"), bRestartWorks);
    Input->SetBoolField(TEXT("passed"), ForwardDistance > 1 && RightDistance > 1 && YawChange > 0.1 && bSpacePauses && bRestartWorks);
    Root->SetObjectField(TEXT("input_test"), Input);
    TArray<TSharedPtr<FJsonValue>> Results;
    FString CSV = TEXT("phase,frame_ms,game_ms,render_ms,rhi_ms,gpu_ms,process_ram_mb,animation_frame,normalized_time\n");
    for (int32 I = 0; I < Samples.Num(); ++I)
    {
        auto Row = MakeShared<FJsonObject>();
        const auto& Data = Samples[I];
        double Sum = 0, Game = 0, Render = 0, GPU = 0, Memory = 0;
        TArray<double> Times; TSet<int32> Frames;
        for (const auto& S : Data)
        {
            Sum += S.FrameMS; Game += S.GameMS; Render += S.RenderMS; GPU += S.GPUMS;
            Memory = FMath::Max(Memory, S.MemoryMB); Times.Add(S.FrameMS); Frames.Add(S.AnimationFrame);
            CSV += FString::Printf(TEXT("%s,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f,%d,%.6f\n"),
                PhaseNames[I], S.FrameMS, S.GameMS, S.RenderMS, S.RHIMS, S.GPUMS, S.MemoryMB, S.AnimationFrame, S.Time);
        }
        Times.Sort();
        Row->SetStringField(TEXT("phase"), PhaseNames[I]); Row->SetNumberField(TEXT("samples"), Data.Num());
        if (!Data.IsEmpty())
        {
            Row->SetNumberField(TEXT("fps"), 1000 * Data.Num() / Sum);
            Row->SetNumberField(TEXT("frame_ms"), Sum / Data.Num());
            Row->SetNumberField(TEXT("p95_frame_ms"), Times[FMath::Min(Times.Num()-1, FMath::FloorToInt(Times.Num()*.95))]);
            Row->SetNumberField(TEXT("game_ms"), Game / Data.Num());
            Row->SetNumberField(TEXT("render_ms"), Render / Data.Num());
            Row->SetNumberField(TEXT("gpu_ms"), GPU / Data.Num());
            Row->SetNumberField(TEXT("peak_process_ram_mb"), Memory);
            Row->SetNumberField(TEXT("distinct_animation_frames"), Frames.Num());
        }
        Results.Add(MakeShared<FJsonValueObject>(Row));
    }
    Root->SetArrayField(TEXT("phases"), Results);
    FString JSON;
    FJsonSerializer::Serialize(Root, TJsonWriterFactory<>::Create(&JSON));
    FFileHelper::SaveStringToFile(JSON, *(OutputFolder / TEXT("summary.json")));
    FFileHelper::SaveStringToFile(CSV, *(OutputFolder / TEXT("frames.csv")));
    UE_LOG(LogTemp, Display, TEXT("GS4D_BENCHMARK_COMPLETE %s"), *OutputFolder);
}
