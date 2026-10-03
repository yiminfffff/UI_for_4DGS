#pragma once
#include "CoreMinimal.h"
#include "Factories/Factory.h"
#include "GS4DFactory.generated.h"

UCLASS()
class UGS4DFactory : public UFactory
{
    GENERATED_BODY()
public:
    UGS4DFactory();
    virtual UObject* FactoryCreateBinary(UClass* Class, UObject* Parent, FName Name, EObjectFlags Flags,
        UObject* Context, const TCHAR* Type, const uint8*& Buffer, const uint8* BufferEnd, FFeedbackContext* Warn) override;
};
