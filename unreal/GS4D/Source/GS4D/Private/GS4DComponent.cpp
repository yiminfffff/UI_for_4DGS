#include "GS4DComponent.h"
#include "DynamicMeshBuilder.h"
#include "PrimitiveSceneProxy.h"
#include "SceneManagement.h"
#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "Engine/World.h"

namespace
{
struct FPoint
{
    FVector Position;
    float Covariance[6];
    float Opacity;
    float SH[48];
};

FLinearColor EvaluateSH(const FPoint& P, FVector D, int32 Degree)
{
    D.Normalize();
    const double X = D.X, Y = D.Y, Z = D.Z;
    double B[16] = {0.28209479177387814};
    if (Degree >= 1) { B[1] = -0.4886025119029199*Y; B[2] = 0.4886025119029199*Z; B[3] = -0.4886025119029199*X; }
    if (Degree >= 2)
    {
        B[4] = 1.0925484305920792*X*Y; B[5] = -1.0925484305920792*Y*Z;
        B[6] = 0.31539156525252005*(2*Z*Z-X*X-Y*Y); B[7] = -1.0925484305920792*X*Z;
        B[8] = 0.5462742152960396*(X*X-Y*Y);
    }
    if (Degree >= 3)
    {
        B[9] = -0.5900435899266435*Y*(3*X*X-Y*Y); B[10] = 2.890611442640554*X*Y*Z;
        B[11] = -0.4570457994644658*Y*(4*Z*Z-X*X-Y*Y); B[12] = 0.3731763325901154*Z*(2*Z*Z-3*X*X-3*Y*Y);
        B[13] = -0.4570457994644658*X*(4*Z*Z-X*X-Y*Y); B[14] = 1.445305721320277*Z*(X*X-Y*Y);
        B[15] = -0.5900435899266435*X*(X*X-3*Y*Y);
    }
    float RGB[3] = {0.5f, 0.5f, 0.5f};
    for (int32 I = 0; I < FMath::Square(Degree+1); ++I)
        for (int32 C = 0; C < 3; ++C) RGB[C] += float(B[I]) * P.SH[I*3+C];
    return FLinearColor(FMath::Clamp(RGB[0],0.f,1.f), FMath::Clamp(RGB[1],0.f,1.f), FMath::Clamp(RGB[2],0.f,1.f), P.Opacity);
}

double Bilinear(const float* C, const FVector& A, const FVector& B)
{
    return A.X*(C[0]*B.X+C[1]*B.Y+C[2]*B.Z)
         + A.Y*(C[1]*B.X+C[3]*B.Y+C[4]*B.Z)
         + A.Z*(C[2]*B.X+C[4]*B.Y+C[5]*B.Z);
}

class FGS4DProxy final : public FPrimitiveSceneProxy
{
    TArray<FPoint> Points;
    UMaterialInterface* Material;
    FMaterialRelevance MaterialRelevance;
    int32 Degree;
public:
    explicit FGS4DProxy(UGS4DComponent* Component) : FPrimitiveSceneProxy(Component),
        Material(Component->GetMaterial(0)), MaterialRelevance(Component->GetMaterialRelevance(GetScene().GetShaderPlatform())),
        Degree(Component->Sequence->SHDegree)
    {
        const UGS4DAsset* Asset = Component->Sequence;
        const int32 Count = Component->MaxPoints > 0 ? FMath::Min(Component->MaxPoints, Asset->PointCount) : Asset->PointCount;
        Points.Reserve(Count);
        const int64 Offset = int64(Component->FrameIndex()) * Asset->PointCount * UGS4DAsset::FloatsPerPoint * sizeof(float);
        for (int32 Index = 0; Index < Count; ++Index)
        {
            const int32 SourceIndex = int32(int64(Index) * Asset->PointCount / Count);
            float V[UGS4DAsset::FloatsPerPoint];
            FMemory::Memcpy(V, Asset->FrameData.GetData() + Offset + int64(SourceIndex)*sizeof(V), sizeof(V));
            FPoint P;
            P.Position = FVector(V[0], V[1], V[2]);
            FMemory::Memcpy(P.Covariance, V+3, sizeof(P.Covariance));
            P.Opacity = V[9];
            FMemory::Memcpy(P.SH, V+10, sizeof(P.SH));
            Points.Add(P);
        }
        if (!Material) Material = UMaterial::GetDefaultMaterial(MD_Surface);
    }
    virtual SIZE_T GetTypeHash() const override { static size_t Unique; return reinterpret_cast<SIZE_T>(&Unique); }
    virtual uint32 GetMemoryFootprint() const override { return sizeof(*this) + Points.GetAllocatedSize(); }
    virtual FPrimitiveViewRelevance GetViewRelevance(const FSceneView* View) const override
    {
        FPrimitiveViewRelevance Result;
        Result.bDrawRelevance = IsShown(View);
        Result.bDynamicRelevance = true;
        Result.bRenderInMainPass = ShouldRenderInMainPass();
        Result.bShadowRelevance = false;
        MaterialRelevance.SetPrimitiveViewRelevance(Result);
        return Result;
    }
    virtual void GetDynamicMeshElements(const TArray<const FSceneView*>& Views, const FSceneViewFamily& Family,
                                       uint32 VisibilityMap, FMeshElementCollector& Collector) const override
    {
        const FMatrix ActorToWorld = GetLocalToWorld();
        const FMatrix WorldToLocal = ActorToWorld.Inverse();
        for (int32 ViewIndex = 0; ViewIndex < Views.Num(); ++ViewIndex)
        {
            if (!(VisibilityMap & (1u << ViewIndex))) continue;
            const FSceneView* View = Views[ViewIndex];
            if (!View->IsPerspectiveProjection()) continue;
            const FMatrix InvView = View->ViewMatrices.GetViewToWorld();
            const FVector Right = InvView.GetScaledAxis(EAxis::X).GetSafeNormal();
            const FVector Up = InvView.GetScaledAxis(EAxis::Y).GetSafeNormal();
            const FVector Forward = InvView.GetScaledAxis(EAxis::Z).GetSafeNormal();
            const FVector Eye = View->ViewMatrices.GetViewOrigin();
            const FVector LocalEye = WorldToLocal.TransformPosition(Eye);
            struct FOrder { int32 Index; double Depth; };
            TArray<FOrder> Order;
            Order.Reserve(Points.Num());
            for (int32 I = 0; I < Points.Num(); ++I)
            {
                const double Z = FVector::DotProduct(ActorToWorld.TransformPosition(Points[I].Position)-Eye, Forward);
                if (Z > 20 && Points[I].Opacity >= 1.f/255) Order.Add({I, Z});
            }
            Order.Sort([](const FOrder& A, const FOrder& B) { return A.Depth > B.Depth; });
            FDynamicMeshBuilder Mesh(View->GetFeatureLevel(), 1, 0, false);
            Mesh.ReserveVertices(Order.Num()*4);
            Mesh.ReserveTriangles(Order.Num()*2);
            const double Focal = 0.5 * View->UnscaledViewRect.Width() * View->ViewMatrices.GetViewToClip().M[0][0];
            for (const FOrder& Item : Order)
            {
                const FPoint& P = Points[Item.Index];
                const FVector Center = ActorToWorld.TransformPosition(P.Position);
                const FVector Delta = Center - Eye;
                const double X = FVector::DotProduct(Delta, Right), Y = FVector::DotProduct(Delta, Up), Z = Item.Depth;
                // Match the native rasterizer's bounded perspective Jacobian.
                const double LimitX = 1.3 / View->ViewMatrices.GetViewToClip().M[0][0];
                const double LimitY = 1.3 / View->ViewMatrices.GetViewToClip().M[1][1];
                const FVector JX = ActorToWorld.GetTransposed().TransformVector(Right - Forward * FMath::Clamp(X/Z, -LimitX, LimitX));
                const FVector JY = ActorToWorld.GetTransposed().TransformVector(Up - Forward * FMath::Clamp(Y/Z, -LimitY, LimitY));
                const double Filter = 0.3 * FMath::Square(Z / FMath::Max(Focal, 1.0));
                const double A = Bilinear(P.Covariance, JX, JX)+Filter;
                const double B = Bilinear(P.Covariance, JX, JY);
                const double C = Bilinear(P.Covariance, JY, JY)+Filter;
                const double Root = FMath::Sqrt(FMath::Max(0.0, FMath::Square(A-C)+4*B*B));
                const double L1 = FMath::Max(1e-8, (A+C+Root)*0.5), L2 = FMath::Max(1e-8, (A+C-Root)*0.5);
                const double Angle = 0.5*FMath::Atan2(2*B,A-C);
                const FVector Axis1 = (Right*FMath::Cos(Angle)+Up*FMath::Sin(Angle))*(3*FMath::Sqrt(L1));
                const FVector Axis2 = (-Right*FMath::Sin(Angle)+Up*FMath::Cos(Angle))*(3*FMath::Sqrt(L2));
                FVector Direction = P.Position - LocalEye;
                Direction.Y *= -1;
                const FColor Color = EvaluateSH(P, Direction, Degree).ToFColor(false);
                const int32 Start = Mesh.AddVertex(FVector3f(Center-Axis1-Axis2), FVector2f(0,0), FVector3f(Right), FVector3f(Up), FVector3f(-Forward), Color);
                Mesh.AddVertex(FVector3f(Center+Axis1-Axis2), FVector2f(1,0), FVector3f(Right), FVector3f(Up), FVector3f(-Forward), Color);
                Mesh.AddVertex(FVector3f(Center+Axis1+Axis2), FVector2f(1,1), FVector3f(Right), FVector3f(Up), FVector3f(-Forward), Color);
                Mesh.AddVertex(FVector3f(Center-Axis1+Axis2), FVector2f(0,1), FVector3f(Right), FVector3f(Up), FVector3f(-Forward), Color);
                Mesh.AddTriangle(Start, Start+1, Start+2);
                Mesh.AddTriangle(Start, Start+2, Start+3);
            }
            if (Order.Num()) Mesh.GetMesh(FMatrix::Identity, Material->GetRenderProxy(), SDPG_World, true, false, ViewIndex, Collector);
        }
    }
};
}

UGS4DComponent::UGS4DComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    bTickInEditor = true;
    CastShadow = false;
    bUseAsOccluder = false;
    SetCollisionEnabled(ECollisionEnabled::NoCollision);
}

int32 UGS4DComponent::FrameIndex() const
{
    if (!Sequence || Sequence->Times.IsEmpty()) return 0;
    int32 Index = 0;
    while (Index+1 < Sequence->Times.Num() && Sequence->Times[Index+1] <= NormalizedTime) ++Index;
    return Index;
}

void UGS4DComponent::SetSequence(UGS4DAsset* Asset)
{
    Sequence = Asset;
    if (Asset && Asset->SplatMaterial) SetMaterial(0, Asset->SplatMaterial);
    DisplayedFrame = INDEX_NONE;
    UpdateBounds();
    MarkRenderStateDirty();
}

void UGS4DComponent::SetNormalizedTime(float Time)
{
    NormalizedTime = FMath::Clamp(Time, 0.f, 1.f);
    if (DisplayedFrame != FrameIndex()) { DisplayedFrame = FrameIndex(); MarkRenderStateDirty(); }
}

void UGS4DComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* TickFunction)
{
    Super::TickComponent(DeltaTime, TickType, TickFunction);
    if (!Sequence) return;
    if (bPlaying && (GetWorld()->IsGameWorld() || bPreviewInEditor))
    {
        float Next = NormalizedTime + DeltaTime*PlaybackRate/FMath::Max(Sequence->DurationSeconds, 0.001f);
        if (Next > 1) { if (bLoop) Next = FMath::Fmod(Next, 1.f); else { Next = 1; bPlaying = false; } }
        SetNormalizedTime(Next);
    }
    else SetNormalizedTime(NormalizedTime);
}

FPrimitiveSceneProxy* UGS4DComponent::CreateSceneProxy()
{
    if (!Sequence || Sequence->PointCount <= 0 || Sequence->FrameCount <= 0 ||
        int64(Sequence->FrameData.Num()) != int64(Sequence->PointCount)*Sequence->FrameCount*UGS4DAsset::FloatsPerPoint*4) return nullptr;
    return new FGS4DProxy(this);
}

FBoxSphereBounds UGS4DComponent::CalcBounds(const FTransform& Transform) const
{
    return FBoxSphereBounds(Sequence ? Sequence->LocalBounds : FBox(FVector(-100), FVector(100))).TransformBy(Transform);
}

#if WITH_EDITOR
void UGS4DComponent::PostEditChangeProperty(FPropertyChangedEvent& Event)
{
    Super::PostEditChangeProperty(Event);
    if (Event.GetPropertyName() == GET_MEMBER_NAME_CHECKED(UGS4DComponent, Sequence))
        SetMaterial(0, Sequence ? Sequence->SplatMaterial.Get() : nullptr);
    UpdateBounds();
    MarkRenderStateDirty();
}
#endif

AGS4DActor::AGS4DActor()
{
    GaussianComponent = CreateDefaultSubobject<UGS4DComponent>(TEXT("GaussianComponent"));
    RootComponent = GaussianComponent;
}
