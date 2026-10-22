#include "GS4DComponent.h"
#include "PrimitiveSceneProxy.h"
#include "PrimitiveUniformShaderParametersBuilder.h"
#include "SceneManagement.h"
#include "MeshElementCollector.h"
#include "LocalVertexFactory.h"
#include "GlobalShader.h"
#include "ShaderParameterStruct.h"
#include "RenderGraphUtils.h"
#include "RenderingThread.h"
#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "ProfilingDebugging/CpuProfilerTrace.h"
#include "Stats/Stats.h"

DECLARE_STATS_GROUP(TEXT("4D Gaussian Playback"), STATGROUP_GS4D, STATCAT_Advanced);
DECLARE_CYCLE_STAT(TEXT("Depth order and index upload"), STAT_GS4DDepthOrder, STATGROUP_GS4D);
DECLARE_CYCLE_STAT(TEXT("GPU projection dispatch setup"), STAT_GS4DProjection, STATGROUP_GS4D);
DECLARE_DWORD_COUNTER_STAT(TEXT("Drawn Gaussians"), STAT_GS4DVisiblePoints, STATGROUP_GS4D);

namespace
{
TAutoConsoleVariable<int32> CVarGS4DInterpolate(TEXT("r.GS4D.Interpolate"), 1,
    TEXT("Interpolate stable-ID attributes between baked samples (1), or hold each sample (0)."), ECVF_RenderThreadSafe);

void FrameBlend(const TArray<float>& Times, float Time, bool bInterpolate, int32& FrameA, int32& FrameB, float& Alpha)
{
    FrameA = 0; FrameB = 0; Alpha = 0;
    if (Times.IsEmpty()) return;
    while (FrameA+1 < Times.Num() && Times[FrameA+1] <= Time) ++FrameA;
    FrameB = FMath::Min(FrameA+1,Times.Num()-1);
    if (bInterpolate && FrameA != FrameB)
        Alpha = FMath::Clamp((Time-Times[FrameA])/FMath::Max(Times[FrameB]-Times[FrameA],SMALL_NUMBER),0.f,1.f);
}

class FGS4DProjectCS : public FGlobalShader
{
    DECLARE_GLOBAL_SHADER(FGS4DProjectCS);
    SHADER_USE_PARAMETER_STRUCT(FGS4DProjectCS, FGlobalShader);
    BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
        SHADER_PARAMETER(uint32, PointCount)
        SHADER_PARAMETER(uint32, SourcePointCount)
        SHADER_PARAMETER(uint32, FrameA)
        SHADER_PARAMETER(uint32, FrameB)
        SHADER_PARAMETER(uint32, SHDegree)
        SHADER_PARAMETER(float, FrameAlpha)
        SHADER_PARAMETER(FVector3f, LocalEye)
        SHADER_PARAMETER(FVector3f, ActorX)
        SHADER_PARAMETER(FVector3f, ActorY)
        SHADER_PARAMETER(FVector3f, ActorZ)
        SHADER_PARAMETER(FVector3f, Right)
        SHADER_PARAMETER(FVector3f, Up)
        SHADER_PARAMETER(FVector3f, Forward)
        SHADER_PARAMETER(FVector3f, LocalRight)
        SHADER_PARAMETER(FVector3f, LocalUp)
        SHADER_PARAMETER(FVector3f, LocalForward)
        SHADER_PARAMETER(FVector2f, PerspectiveLimit)
        SHADER_PARAMETER(float, Focal)
        SHADER_PARAMETER_SRV(Buffer<float>, SourceData)
        SHADER_PARAMETER_SRV(Buffer<uint>, SourceIndices)
        SHADER_PARAMETER_UAV(RWBuffer<float>, OutPositions)
        SHADER_PARAMETER_UAV(RWBuffer<uint>, OutColors)
        SHADER_PARAMETER_UAV(RWBuffer<uint>, OutTangents)
    END_SHADER_PARAMETER_STRUCT()
    static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& Parameters)
    {
        return IsFeatureLevelSupported(Parameters.Platform, ERHIFeatureLevel::SM5);
    }
};
IMPLEMENT_GLOBAL_SHADER(FGS4DProjectCS, "/Plugin/GS4D/Private/GS4DProject.usf", "MainCS", SF_Compute);

// Persistent GPU streams replace FDynamicMeshBuilder's per-view CPU mesh copies.
class FGS4DVertexBuffer final : public FVertexBuffer
{
public:
    uint32 Size = 0;
    EPixelFormat Format = PF_Unknown;
    bool bWritable = false;
    FShaderResourceViewRHIRef SRV;
    FUnorderedAccessViewRHIRef UAV;
    virtual void InitRHI(FRHICommandListBase& RHICmdList) override
    {
        const FRHIBufferCreateDesc Desc = FRHIBufferCreateDesc::CreateVertex(TEXT("GS4DVertexBuffer"), Size)
            .AddUsage(BUF_Static | BUF_ShaderResource | (bWritable ? BUF_UnorderedAccess : BUF_None))
            .SetInitialState(bWritable ? ERHIAccess::UAVCompute : ERHIAccess::SRVMask | ERHIAccess::VertexOrIndexBuffer);
        VertexBufferRHI = RHICmdList.CreateBuffer(Desc);
        SRV = RHICmdList.CreateShaderResourceView(VertexBufferRHI,
            FRHIViewDesc::CreateBufferSRV().SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(Format));
        if (bWritable)
            UAV = RHICmdList.CreateUnorderedAccessView(VertexBufferRHI,
                FRHIViewDesc::CreateBufferUAV().SetType(FRHIViewDesc::EBufferType::Typed)
                    .SetFormat(Format == PF_R32_FLOAT ? PF_R32_FLOAT : PF_R32_UINT));
    }
    virtual void ReleaseRHI() override
    {
        UAV.SafeRelease(); SRV.SafeRelease(); FVertexBuffer::ReleaseRHI();
    }
    void Initialize(FRHICommandListBase& RHICmdList, uint32 InSize, EPixelFormat InFormat, bool bInWritable = false)
    {
        Size = InSize; Format = InFormat; bWritable = bInWritable; InitResource(RHICmdList);
    }
    void Upload(FRHICommandListBase& RHICmdList, const void* Data, uint32 Bytes)
    {
        void* Dest = RHICmdList.LockBuffer(VertexBufferRHI, 0, Bytes, RLM_WriteOnly);
        FMemory::Memcpy(Dest, Data, Bytes);
        RHICmdList.UnlockBuffer(VertexBufferRHI);
    }
};

class FGS4DIndexBuffer final : public FIndexBuffer
{
public:
    uint32 Size = 0;
    virtual void InitRHI(FRHICommandListBase& RHICmdList) override
    {
        IndexBufferRHI = RHICmdList.CreateBuffer(FRHIBufferCreateDesc::CreateIndex(TEXT("GS4DSortedIndices"), Size, sizeof(uint32))
            .AddUsage(BUF_Dynamic).SetInitialState(ERHIAccess::VertexOrIndexBuffer));
    }
};

struct FGS4DViewResources
{
    FGS4DVertexBuffer Positions, Colors, Tangents, UVs;
    FGS4DIndexBuffer Indices;
    FLocalVertexFactory VertexFactory;
    FMatrix CachedView = FMatrix::Identity, CachedProjection = FMatrix::Identity, CachedTransform = FMatrix::Identity;
    int32 CachedFrameA = INDEX_NONE, CachedFrameB = INDEX_NONE, CachedWidth = 0;
    float CachedAlpha = -1;
    uint32 VisibleCount = 0;
    bool bProjected = false;
    explicit FGS4DViewResources(ERHIFeatureLevel::Type FeatureLevel) : VertexFactory(FeatureLevel, "GS4DVertexFactory") {}
    void Initialize(FRHICommandListBase& RHICmdList, int32 Count)
    {
        Positions.Initialize(RHICmdList, Count*4*sizeof(FVector3f), PF_R32_FLOAT, true);
        Colors.Initialize(RHICmdList, Count*4*sizeof(FColor), PF_R8G8B8A8, true);
        Tangents.Initialize(RHICmdList, Count*8*sizeof(FPackedNormal), PF_R8G8B8A8_SNORM, true);
        UVs.Initialize(RHICmdList, Count*4*sizeof(FVector2f), PF_G32R32F);
        TArray<FVector2f> Corners;
        Corners.SetNumUninitialized(Count*4);
        for (int32 I = 0; I < Count; ++I)
        {
            Corners[I*4] = FVector2f(0,0); Corners[I*4+1] = FVector2f(1,0);
            Corners[I*4+2] = FVector2f(1,1); Corners[I*4+3] = FVector2f(0,1);
        }
        UVs.Upload(RHICmdList, Corners.GetData(), UVs.Size);
        Indices.Size = Count*6*sizeof(uint32);
        Indices.InitResource(RHICmdList);
        FLocalVertexFactory::FDataType Data;
        Data.PositionComponent = FVertexStreamComponent(&Positions, 0, sizeof(FVector3f), VET_Float3);
        Data.PositionComponentSRV = Positions.SRV;
        Data.ColorComponent = FVertexStreamComponent(&Colors, 0, sizeof(FColor), VET_Color, EVertexStreamUsage::ManualFetch);
        Data.ColorComponentsSRV = Colors.SRV;
        Data.TangentBasisComponents[0] = FVertexStreamComponent(&Tangents, 0, 2*sizeof(FPackedNormal), VET_PackedNormal, EVertexStreamUsage::ManualFetch);
        Data.TangentBasisComponents[1] = FVertexStreamComponent(&Tangents, sizeof(FPackedNormal), 2*sizeof(FPackedNormal), VET_PackedNormal, EVertexStreamUsage::ManualFetch);
        Data.TangentsSRV = Tangents.SRV;
        Data.TextureCoordinates.Add(FVertexStreamComponent(&UVs, 0, sizeof(FVector2f), VET_Float2, EVertexStreamUsage::ManualFetch));
        Data.TextureCoordinatesSRV = UVs.SRV;
        Data.NumTexCoords = 1; Data.LightMapCoordinateIndex = 0;
        VertexFactory.SetData(RHICmdList, Data);
        VertexFactory.InitResource(RHICmdList);
    }
    ~FGS4DViewResources()
    {
        VertexFactory.ReleaseResource(); Indices.ReleaseResource(); UVs.ReleaseResource();
        Tangents.ReleaseResource(); Colors.ReleaseResource(); Positions.ReleaseResource();
    }
};

// Captures without a persistent view state must not overwrite another view's
// streams while its mesh batch is still waiting to draw.
struct FGS4DTransientViewResources final : public FOneFrameResource
{
    FGS4DViewResources Resources;
    FGS4DTransientViewResources(FRHICommandListBase& RHICmdList, ERHIFeatureLevel::Type FeatureLevel, int32 Count)
        : Resources(FeatureLevel) { Resources.Initialize(RHICmdList,Count); }
};

class FGS4DProxy final : public FPrimitiveSceneProxy
{
    // Snapshot on the game thread: never read asset data from the render thread.
    TArray<uint8> InitialSourceData;
    TArray<uint32> InitialSourceIndices;
    TArray<FVector4f> SortSamples;
    TArray<float> Times;
    FGS4DVertexBuffer SourceBuffer;
    FGS4DVertexBuffer SourceIndexBuffer;
    UMaterialInterface* Material;
    FMaterialRelevance MaterialRelevance;
    int32 Count, SourceCount, Degree;
    float Time;
    mutable TMap<uint64, TUniquePtr<FGS4DViewResources>> ViewResources;
public:
    explicit FGS4DProxy(UGS4DComponent* Component) : FPrimitiveSceneProxy(Component),
        Material(Component->GetMaterial(0)), MaterialRelevance(Component->GetMaterialRelevance(GetScene().GetShaderPlatform())),
        Count(Component->MaxPoints > 0 ? FMath::Min(Component->MaxPoints, Component->Sequence->PointCount) : Component->Sequence->PointCount),
        SourceCount(Component->Sequence->PointCount), Degree(FMath::Clamp(Component->Sequence->SHDegree, 0, 3)), Time(Component->NormalizedTime)
    {
        const UGS4DAsset* Asset = Component->Sequence;
        InitialSourceData = Asset->FrameData; Times = Asset->Times;
        InitialSourceIndices.SetNumUninitialized(Count);
        for (int32 I = 0; I < Count; ++I) InitialSourceIndices[I] = uint32(int64(I)*SourceCount/Count);
        SortSamples.SetNumUninitialized(Count*Asset->FrameCount);
        for (int32 Frame = 0; Frame < Asset->FrameCount; ++Frame)
            for (int32 I = 0; I < Count; ++I)
            {
                const int32 SourceIndex = InitialSourceIndices[I];
                const uint8* Source = InitialSourceData.GetData()+(int64(Frame)*SourceCount+SourceIndex)*UGS4DAsset::FloatsPerPoint*sizeof(float);
                float XYZ[3], Opacity;
                FMemory::Memcpy(XYZ, Source, sizeof(XYZ));
                FMemory::Memcpy(&Opacity, Source+9*sizeof(float), sizeof(Opacity));
                SortSamples[Frame*Count+I] = FVector4f(XYZ[0],XYZ[1],XYZ[2],Opacity);
            }
        if (!Material) Material = UMaterial::GetDefaultMaterial(MD_Surface);
        bSupportsParallelGDME = false;
    }
    virtual ~FGS4DProxy() { ViewResources.Empty(); SourceIndexBuffer.ReleaseResource(); SourceBuffer.ReleaseResource(); }
    virtual void CreateRenderThreadResources(FRHICommandListBase& RHICmdList) override
    {
        SourceBuffer.Initialize(RHICmdList, InitialSourceData.Num(), PF_R32_FLOAT);
        SourceBuffer.Upload(RHICmdList, InitialSourceData.GetData(), InitialSourceData.Num());
        SourceIndexBuffer.Initialize(RHICmdList,InitialSourceIndices.Num()*sizeof(uint32),PF_R32_UINT);
        SourceIndexBuffer.Upload(RHICmdList,InitialSourceIndices.GetData(),InitialSourceIndices.Num()*sizeof(uint32));
        InitialSourceIndices.Empty();
        InitialSourceData.Empty();
    }
    void SetTime_RenderThread(float InTime) { Time = InTime; }
    virtual SIZE_T GetTypeHash() const override { static size_t Unique; return reinterpret_cast<SIZE_T>(&Unique); }
    virtual uint32 GetMemoryFootprint() const override
    {
        return sizeof(*this)+SortSamples.GetAllocatedSize()+Times.GetAllocatedSize()+InitialSourceData.GetAllocatedSize();
    }
    virtual FPrimitiveViewRelevance GetViewRelevance(const FSceneView* View) const override
    {
        FPrimitiveViewRelevance Result;
        Result.bDrawRelevance = IsShown(View); Result.bDynamicRelevance = true;
        Result.bRenderInMainPass = ShouldRenderInMainPass(); Result.bShadowRelevance = false;
        MaterialRelevance.SetPrimitiveViewRelevance(Result);
        return Result;
    }
    virtual void GetDynamicMeshElements(const TArray<const FSceneView*>& Views, const FSceneViewFamily& Family,
        uint32 VisibilityMap, FMeshElementCollector& Collector) const override
    {
        TRACE_CPUPROFILER_EVENT_SCOPE(GS4D_Gather);
        if (!SourceBuffer.SRV.IsValid()) return;
        FRHICommandList& RHICmdList = Collector.GetRHICommandList();
        int32 FrameA,FrameB;
        float Alpha;
        FrameBlend(Times,Time,CVarGS4DInterpolate.GetValueOnRenderThread()!=0,FrameA,FrameB,Alpha);
        const FMatrix ActorToWorld = GetLocalToWorld(), WorldToLocal = ActorToWorld.Inverse();
        for (int32 ViewIndex = 0; ViewIndex < Views.Num(); ++ViewIndex)
        {
            if (!(VisibilityMap & (1u<<ViewIndex))) continue;
            const FSceneView* View = Views[ViewIndex];
            if (!View->IsPerspectiveProjection()) continue;
            FGS4DViewResources* ViewResource;
            if (View->State)
            {
                const uint64 ViewKey = (uint64(View->GetViewKey())<<32) | uint32(View->StereoViewIndex+1);
                TUniquePtr<FGS4DViewResources>& Entry = ViewResources.FindOrAdd(ViewKey);
                if (!Entry)
                {
                    Entry = MakeUnique<FGS4DViewResources>(View->GetFeatureLevel());
                    Entry->Initialize(RHICmdList,Count);
                }
                ViewResource = Entry.Get();
            }
            else ViewResource = &Collector.AllocateOneFrameResource<FGS4DTransientViewResources>(RHICmdList,View->GetFeatureLevel(),Count).Resources;
            FGS4DViewResources& Resources = *ViewResource;
            const FMatrix& ViewMatrix = View->ViewMatrices.GetWorldToView();
            const FMatrix& Projection = View->ViewMatrices.GetViewToClip();
            if (Resources.CachedFrameA != FrameA || Resources.CachedFrameB != FrameB || Resources.CachedAlpha != Alpha ||
                Resources.CachedWidth != View->UnscaledViewRect.Width() || !Resources.CachedView.Equals(ViewMatrix,0) ||
                !Resources.CachedProjection.Equals(Projection,0) || !Resources.CachedTransform.Equals(ActorToWorld,0))
            {
                const FMatrix InvView = View->ViewMatrices.GetViewToWorld();
                const FVector Right = InvView.GetScaledAxis(EAxis::X).GetSafeNormal(), Up = InvView.GetScaledAxis(EAxis::Y).GetSafeNormal();
                const FVector Forward = InvView.GetScaledAxis(EAxis::Z).GetSafeNormal();
                const FVector LocalEye = WorldToLocal.TransformPosition(View->ViewMatrices.GetViewOrigin());
                const FVector DepthAxis = ActorToWorld.GetTransposed().TransformVector(Forward);
                struct FOrder { uint32 Index; float Depth; };
                TArray<FOrder> Order;
                {
                    SCOPE_CYCLE_COUNTER(STAT_GS4DDepthOrder);
                    TRACE_CPUPROFILER_EVENT_SCOPE(GS4D_DepthSort);
                    Order.Reserve(Count);
                    const FVector3f Eye(LocalEye), Axis(DepthAxis);
                    const FVector4f* SamplesA = SortSamples.GetData()+FrameA*Count;
                    const FVector4f* SamplesB = SortSamples.GetData()+FrameB*Count;
                    for (int32 I = 0; I < Count; ++I)
                    {
                        const FVector4f P = FMath::Lerp(SamplesA[I],SamplesB[I],Alpha);
                        const float Z = FVector3f::DotProduct(FVector3f(P.X,P.Y,P.Z)-Eye,Axis);
                        if (Z > 20 && P.W >= 1.f/255) Order.Add({uint32(I),Z});
                    }
                    Order.Sort([](const FOrder& A,const FOrder& B) { return A.Depth > B.Depth; });
                    Resources.VisibleCount = Order.Num();
                    if (Order.Num())
                    {
                        uint32* Indices = static_cast<uint32*>(RHICmdList.LockBuffer(Resources.Indices.IndexBufferRHI,0,Order.Num()*6*sizeof(uint32),RLM_WriteOnly));
                        for (int32 I = 0; I < Order.Num(); ++I)
                        {
                            const uint32 V = Order[I].Index*4;
                            Indices[I*6] = V; Indices[I*6+1] = V+1; Indices[I*6+2] = V+2;
                            Indices[I*6+3] = V; Indices[I*6+4] = V+2; Indices[I*6+5] = V+3;
                        }
                        RHICmdList.UnlockBuffer(Resources.Indices.IndexBufferRHI);
                    }
                }
                {
                    SCOPE_CYCLE_COUNTER(STAT_GS4DProjection);
                    TRACE_CPUPROFILER_EVENT_SCOPE(GS4D_GPUProjection);
                    const ERHIAccess ReadState = ERHIAccess::VertexOrIndexBuffer | ERHIAccess::SRVMask;
                    const ERHIAccess PreviousState = Resources.bProjected ? ReadState : ERHIAccess::UAVCompute;
                    RHICmdList.Transition({FRHITransitionInfo(Resources.Positions.UAV,PreviousState,ERHIAccess::UAVCompute),
                        FRHITransitionInfo(Resources.Colors.UAV,PreviousState,ERHIAccess::UAVCompute),
                        FRHITransitionInfo(Resources.Tangents.UAV,PreviousState,ERHIAccess::UAVCompute)});
                    FGS4DProjectCS::FParameters Params;
                    Params.PointCount = Count; Params.SourcePointCount = SourceCount;
                    Params.FrameA = FrameA; Params.FrameB = FrameB; Params.FrameAlpha = Alpha; Params.SHDegree = Degree;
                    Params.LocalEye = FVector3f(LocalEye);
                    Params.ActorX = FVector3f(ActorToWorld.GetScaledAxis(EAxis::X));
                    Params.ActorY = FVector3f(ActorToWorld.GetScaledAxis(EAxis::Y));
                    Params.ActorZ = FVector3f(ActorToWorld.GetScaledAxis(EAxis::Z));
                    Params.Right = FVector3f(Right); Params.Up = FVector3f(Up); Params.Forward = FVector3f(Forward);
                    Params.LocalRight = FVector3f(FVector(WorldToLocal.TransformVector(Right)));
                    Params.LocalUp = FVector3f(FVector(WorldToLocal.TransformVector(Up)));
                    Params.LocalForward = FVector3f(FVector(WorldToLocal.TransformVector(Forward)));
                    Params.PerspectiveLimit = FVector2f(1.3f/Projection.M[0][0],1.3f/Projection.M[1][1]);
                    Params.Focal = FMath::Max(1.f,float(0.5*View->UnscaledViewRect.Width()*Projection.M[0][0]));
                    Params.SourceData = SourceBuffer.SRV;
                    Params.SourceIndices = SourceIndexBuffer.SRV;
                    Params.OutPositions = Resources.Positions.UAV; Params.OutColors = Resources.Colors.UAV; Params.OutTangents = Resources.Tangents.UAV;
                    TShaderMapRef<FGS4DProjectCS> Shader(GetGlobalShaderMap(View->GetFeatureLevel()));
                    FComputeShaderUtils::Dispatch(RHICmdList,Shader,Params,FIntVector(FMath::DivideAndRoundUp(Count,64),1,1));
                    RHICmdList.Transition({FRHITransitionInfo(Resources.Positions.UAV,ERHIAccess::UAVCompute,ReadState),
                        FRHITransitionInfo(Resources.Colors.UAV,ERHIAccess::UAVCompute,ReadState),
                        FRHITransitionInfo(Resources.Tangents.UAV,ERHIAccess::UAVCompute,ReadState)});
                    Resources.bProjected = true;
                }
                Resources.CachedFrameA = FrameA; Resources.CachedFrameB = FrameB; Resources.CachedAlpha = Alpha;
                Resources.CachedView = ViewMatrix; Resources.CachedProjection = Projection; Resources.CachedTransform = ActorToWorld;
                Resources.CachedWidth = View->UnscaledViewRect.Width();
            }
            INC_DWORD_STAT_BY(STAT_GS4DVisiblePoints, Resources.VisibleCount);
            if (!Resources.VisibleCount) continue;
            FMeshBatch& Mesh = Collector.AllocateMesh();
            FMeshBatchElement& Batch = Mesh.Elements[0];
            Mesh.VertexFactory = &Resources.VertexFactory; Mesh.MaterialRenderProxy = Material->GetRenderProxy();
            Mesh.Type = PT_TriangleList; Mesh.DepthPriorityGroup = SDPG_World;
            Mesh.bDisableBackfaceCulling = true; Mesh.CastShadow = false; Mesh.bCanApplyViewModeOverrides = false;
            Mesh.ReverseCulling = IsLocalToWorldDeterminantNegative();
            Batch.IndexBuffer = &Resources.Indices; Batch.FirstIndex = 0; Batch.NumPrimitives = Resources.VisibleCount*2;
            Batch.MinVertexIndex = 0; Batch.MaxVertexIndex = Count*4-1;
            FDynamicPrimitiveUniformBuffer& Uniform = Collector.AllocateOneFrameResource<FDynamicPrimitiveUniformBuffer>();
            FPrimitiveUniformShaderParametersBuilder Builder;
            BuildUniformShaderParameters(Builder); Uniform.Set(RHICmdList,Builder);
            Batch.PrimitiveUniformBufferResource = &Uniform.UniformBuffer;
            Collector.AddMesh(ViewIndex,Mesh);
        }
    }
};
}

UGS4DComponent::UGS4DComponent()
{
    PrimaryComponentTick.bCanEverTick = true; bTickInEditor = true;
    CastShadow = false; bUseAsOccluder = false;
    SetCollisionEnabled(ECollisionEnabled::NoCollision);
}

int32 UGS4DComponent::FrameIndex() const
{
    if (!Sequence || Sequence->Times.IsEmpty()) return 0;
    int32 Index = 0;
    while (Index+1 < Sequence->Times.Num() && Sequence->Times[Index+1] <= NormalizedTime) ++Index;
    return Index;
}

void UGS4DComponent::GetInterpolationState(int32& OutFrameA,int32& OutFrameB,float& OutAlpha) const
{
    OutFrameA = 0; OutFrameB = 0; OutAlpha = 0;
    if (Sequence) FrameBlend(Sequence->Times,NormalizedTime,CVarGS4DInterpolate.GetValueOnGameThread()!=0,OutFrameA,OutFrameB,OutAlpha);
}

void UGS4DComponent::SetSequence(UGS4DAsset* Asset)
{
    Sequence = Asset;
    if (Asset && Asset->SplatMaterial) SetMaterial(0,Asset->SplatMaterial);
    SubmittedTime = -1; UpdateBounds(); MarkRenderStateDirty();
}

void UGS4DComponent::SetNormalizedTime(float InTime)
{
    NormalizedTime = FMath::Clamp(InTime,0.f,1.f); PlaybackPhase = NormalizedTime;
    if (SubmittedTime != NormalizedTime)
    {
        SubmittedTime = NormalizedTime; MarkRenderDynamicDataDirty();
    }
}

void UGS4DComponent::SendRenderDynamicData_Concurrent()
{
    Super::SendRenderDynamicData_Concurrent();
    if (SceneProxy)
    {
        FGS4DProxy* Proxy = static_cast<FGS4DProxy*>(SceneProxy);
        const float InTime = NormalizedTime;
        ENQUEUE_RENDER_COMMAND(GS4DSetPlaybackTime)([Proxy,InTime](FRHICommandListImmediate& RHICmdList) { Proxy->SetTime_RenderThread(InTime); });
    }
}

void UGS4DComponent::TickComponent(float DeltaTime,ELevelTick TickType,FActorComponentTickFunction* TickFunction)
{
    Super::TickComponent(DeltaTime,TickType,TickFunction);
    if (!Sequence) return;
    if (bPlaying && (GetWorld()->IsGameWorld() || bPreviewInEditor))
    {
        if (!FMath::IsNearlyEqual(NormalizedTime,FMath::Clamp(PlaybackPhase,0.f,1.f))) PlaybackPhase = NormalizedTime;
        float Next = PlaybackPhase+DeltaTime*PlaybackRate/FMath::Max(Sequence->DurationSeconds,0.001f);
        if (bLoop)
        {
            const int32 Last = Sequence->Times.Num()-1;
            const float Hold = Last > 0 ? FMath::Max(Sequence->Times[Last]-Sequence->Times[Last-1],0.f) : 0.f;
            Next = FMath::Fmod(Next,1.f+Hold);
        }
        else if (Next >= 1) { Next = 1; bPlaying = false; }
        SetNormalizedTime(FMath::Min(Next,1.f)); PlaybackPhase = Next;
    }
    else SetNormalizedTime(NormalizedTime);
}

FPrimitiveSceneProxy* UGS4DComponent::CreateSceneProxy()
{
    if (!Sequence || Sequence->PointCount <= 0 || Sequence->FrameCount <= 0 || Sequence->Times.Num() != Sequence->FrameCount ||
        int64(Sequence->FrameData.Num()) != int64(Sequence->PointCount)*Sequence->FrameCount*UGS4DAsset::FloatsPerPoint*4) return nullptr;
    return new FGS4DProxy(this);
}

FBoxSphereBounds UGS4DComponent::CalcBounds(const FTransform& Transform) const
{
    return FBoxSphereBounds(Sequence ? Sequence->LocalBounds : FBox(FVector(-100),FVector(100))).TransformBy(Transform);
}

#if WITH_EDITOR
void UGS4DComponent::PostEditChangeProperty(FPropertyChangedEvent& Event)
{
    Super::PostEditChangeProperty(Event);
    if (Event.GetPropertyName() == GET_MEMBER_NAME_CHECKED(UGS4DComponent,Sequence))
        SetMaterial(0,Sequence ? Sequence->SplatMaterial.Get() : nullptr);
    UpdateBounds(); MarkRenderStateDirty();
}
#endif

AGS4DActor::AGS4DActor()
{
    GaussianComponent = CreateDefaultSubobject<UGS4DComponent>(TEXT("GaussianComponent"));
    RootComponent = GaussianComponent;
}
