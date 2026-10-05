// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal freestanding Windows VST2 fixture: halves its input, like gain.cpp.
// The AEffect layout is the published VST 2.4 one. Not a product plug-in.
using intptr = __INTPTR_TYPE__;
struct AEffect;
using HostCallback = intptr (*)(AEffect*, int, int, intptr, void*, float);
struct AEffect {
    int magic;
    intptr (*dispatcher)(AEffect*, int, int, intptr, void*, float);
    void (*process)(AEffect*, float**, float**, int);
    void (*setParameter)(AEffect*, int, float);
    float (*getParameter)(AEffect*, int);
    int numPrograms, numParams, numInputs, numOutputs, flags;
    intptr reserved1, reserved2;
    int initialDelay, realQualities, offQualities;
    float ioRatio;
    void* object;
    void* user;
    int uniqueID, version;
    void (*processReplacing)(AEffect*, float**, float**, int);
    void (*processDoubleReplacing)(AEffect*, double**, double**, int);
    char future[56];
};

extern "C" void* memset(void* d, int c, __SIZE_TYPE__ n) {for (__SIZE_TYPE__ i = 0; i < n; ++i) static_cast<char*>(d)[i] = c; return d;}
static void text(void* d, const char* s) {char* out = static_cast<char*>(d); while ((*out++ = *s++)) {}}
static constexpr int magic = ('V' << 24) | ('s' << 16) | ('t' << 8) | 'P';
static constexpr int unique = ('P' << 24) | ('g' << 16) | ('G' << 8) | '2';

static void halve(AEffect*, float** in, float** out, int frames) {
    for (int c = 0; c < 2; ++c) for (int s = 0; s < frames; ++s) out[c][s] = in[c][s] * 0.5f;
}
static void set_parameter(AEffect*, int, float) {}
static float get_parameter(AEffect*, int) {return 0.0f;}

static intptr dispatch(AEffect*, int opcode, int, intptr, void* data, float) {
    switch (opcode) {
        case 35: return 1;  // effGetPlugCategory: a plain effect
        case 45: text(data, "Plugg Test Gain 2"); return 1;  // effGetEffectName
        case 47: text(data, "Plugg Tests"); return 1;  // effGetVendorString
        case 48: text(data, "Plugg Test Gain 2"); return 1;  // effGetProductString
        case 49: return 1000;  // effGetVendorVersion
        case 58: return 2400;  // effGetVstVersion
        default: return 0;
    }
}

extern "C" __declspec(dllexport) AEffect* VSTPluginMain(HostCallback) {
    // One effect per call, from a small pool; a probe or test needs only a few.
    static AEffect pool[16];
    static int used = 0;
    if (used == 16) return nullptr;
    AEffect* effect = &pool[used++];
    memset(effect, 0, sizeof(*effect));
    effect->magic = magic;
    effect->dispatcher = dispatch;
    effect->process = halve;
    effect->setParameter = set_parameter;
    effect->getParameter = get_parameter;
    effect->numPrograms = 1;
    effect->numInputs = effect->numOutputs = 2;
    effect->flags = 1 << 4;  // effFlagsCanReplacing
    effect->ioRatio = 1.0f;
    effect->uniqueID = unique;
    effect->version = 1000;
    effect->processReplacing = halve;
    return effect;
}
extern "C" int __stdcall DllMain(void*, unsigned, void*) {return 1;}
extern "C" { int _fltused = 0; }
