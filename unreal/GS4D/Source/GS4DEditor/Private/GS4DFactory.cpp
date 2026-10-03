#include "GS4DFactory.h"
#include "GS4DAsset.h"
#include "Modules/ModuleManager.h"

IMPLEMENT_MODULE(FDefaultModuleImpl, GS4DEditor)

UGS4DFactory::UGS4DFactory()
{
    SupportedClass = UGS4DAsset::StaticClass();
    bCreateNew = false;
    bEditorImport = true;
    Formats.Add(TEXT("gs4d;Baked 4D Gaussian Sequence"));
}

UObject* UGS4DFactory::FactoryCreateBinary(UClass* Class, UObject* Parent, FName Name, EObjectFlags Flags,
    UObject* Context, const TCHAR* Type, const uint8*& Buffer, const uint8* BufferEnd, FFeedbackContext* Warn)
{
    const int64 Size = BufferEnd-Buffer;
    if (Size < 32 || FMemory::Memcmp(Buffer,"GS4D001\0",8)) return nullptr;
    uint32 Header[4];
    float Timing[2];
    FMemory::Memcpy(Header, Buffer+8, sizeof(Header));
    FMemory::Memcpy(Timing, Buffer+24, sizeof(Timing));
    const uint32 Version = Header[0], Points = Header[1], Frames = Header[2], Degree = Header[3];
    if (Version != 1 || Points == 0 || Points > 500000 || Frames < 2 || Frames > 10000 || Degree > 3 ||
        !FMath::IsFinite(Timing[0]) || !FMath::IsFinite(Timing[1]) || Timing[0] <= 0 || Timing[1] <= 0) return nullptr;
    const int64 Bytes = int64(Points)*Frames*UGS4DAsset::FloatsPerPoint*4;
    if (Bytes > MAX_int32 || Size != 32+int64(Frames)*4+Bytes) return nullptr;
    TArray<float> Times;
    Times.SetNumUninitialized(Frames);
    FMemory::Memcpy(Times.GetData(), Buffer+32, Frames*4);
    for (uint32 I=0; I<Frames; ++I)
        if (!FMath::IsFinite(Times[I]) || Times[I]<0 || Times[I]>1 || (I>0 && Times[I]<=Times[I-1])) return nullptr;
    FBox Bounds(ForceInit);
    const uint8* Payload = Buffer+32+Frames*4;
    for (int64 I=0; I<int64(Points)*Frames; ++I)
    {
        float V[UGS4DAsset::FloatsPerPoint];
        FMemory::Memcpy(V, Payload+I*sizeof(V), sizeof(V));
        for (float Value : V) if (!FMath::IsFinite(Value)) return nullptr;
        if (V[3]<0 || V[6]<0 || V[8]<0 || V[9]<0 || V[9]>1) return nullptr;
        const FVector P(V[0],V[1],V[2]);
        const FVector Radius(3*FMath::Sqrt(V[3]),3*FMath::Sqrt(V[6]),3*FMath::Sqrt(V[8]));
        Bounds += P-Radius;
        Bounds += P+Radius;
    }
    UGS4DAsset* Asset = NewObject<UGS4DAsset>(Parent, Class, Name, Flags);
    Asset->PointCount = Points; Asset->FrameCount = Frames; Asset->SHDegree = Degree;
    Asset->SourceFPS = Timing[0]; Asset->DurationSeconds = Timing[1];
    Asset->Times = MoveTemp(Times); Asset->LocalBounds = Bounds; Asset->SourceFile = GetCurrentFilename();
    Asset->FrameData.Append(Payload, int32(Bytes));
    return Asset;
}
