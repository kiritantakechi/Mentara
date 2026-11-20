/*
 * Minimal Syringe hook ABI, as read by Syringe 0.7 and SyringeEx.
 *
 * Syringe injects every DLL in the game directory that carries a
 * `.syhks00` section. Each entry names an exported function to call
 * when execution reaches `address`; the `size` bytes it overwrites are
 * replayed when the hook returns 0, and any other return value is the
 * address to continue at.
 */
#ifndef MENTARA_SYRINGE_H
#define MENTARA_SYRINGE_H

typedef unsigned long DWORD;

/* Register snapshot handed to a hook: origin, flags, then pushad order. */
typedef struct REGISTERS {
    DWORD origin;
    DWORD flags;
    DWORD EDI, ESI, EBP, ESP, EBX, EDX, ECX, EAX;
} REGISTERS;

typedef struct HookDecl {
    unsigned int address;
    unsigned int size;
    const char *name;
} HookDecl;

#pragma section(".syhks00", read, write)

#define DEFINE_HOOK(address, name, size)                                \
    __declspec(dllexport) DWORD __cdecl name(REGISTERS *R);             \
    __declspec(allocate(".syhks00")) HookDecl hook_decl_##name = {      \
        (address), (size), #name};                                      \
    __declspec(dllexport) DWORD __cdecl name(REGISTERS *R)

#endif
