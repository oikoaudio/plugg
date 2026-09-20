// SPDX-License-Identifier: GPL-3.0-or-later
// Disposable VST3 factory probe; --audio additionally verifies the test effect.
#include <dlfcn.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <cstring>
#include <cmath>
#include <atomic>
#include <cstdlib>
#include <sys/prctl.h>
#include <unistd.h>
#include <pluginterfaces/vst/ivsthostapplication.h>
#include <pluginterfaces/base/ipluginbase.h>
#include <pluginterfaces/vst/ivstcomponent.h>
#include <pluginterfaces/vst/ivstaudioprocessor.h>

using namespace Steinberg;
using namespace Steinberg::Vst;

class TestHost final : public IHostApplication {
    std::atomic<uint32> refs{1};
public:
    tresult PLUGIN_API queryInterface(const TUID id, void** object) override {
        *object = nullptr;
        if (FUnknownPrivate::iidEqual(id, IHostApplication::iid) || FUnknownPrivate::iidEqual(id, FUnknown::iid)) {
            *object = static_cast<IHostApplication*>(this); addRef(); return kResultOk;
        }
        return kNoInterface;
    }
    uint32 PLUGIN_API addRef() override { return ++refs; }
    uint32 PLUGIN_API release() override { return --refs; }
    tresult PLUGIN_API getName(String128 name) override {
        const char* value = "Plugg Test";
        unsigned i=0; do { name[i]=value[i]; } while(value[i++]);
        return kResultOk;
    }
    tresult PLUGIN_API createInstance(TUID, TUID, void** object) override { *object=nullptr; return kNoInterface; }
};

static std::string quoted(const char* text, size_t capacity) {
    std::string out = "\"";
    const char* hex = "0123456789abcdef";
    for (size_t n=0; n<capacity && text[n]; ++n) {
        const auto c = static_cast<unsigned char>(text[n]);
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c < 32 || c >= 128) { out += "\\u00"; out += hex[c>>4]; out += hex[c&15]; }
        else out += c;
    }
    return out + "\"";
}

static void progress(const char* stage) {
    if (std::getenv("PLUGG_SCAN_TRACE")) std::cerr << "SCAN_STAGE " << stage << std::endl;
}

int main(int argc, char** argv) {
    if (std::getenv("PLUGG_SCAN_TRACE")) prctl(PR_SET_PTRACER, getppid(), 0, 0, 0);
    progress("load");
    if (argc < 3) return 64;
    void* lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!lib) { std::cerr << dlerror() << '\n'; return 1; }
    auto entry = reinterpret_cast<bool(*)(void*)>(dlsym(lib, "ModuleEntry"));
    auto exit = reinterpret_cast<bool(*)()>(dlsym(lib, "ModuleExit"));
    auto factory_fn = reinterpret_cast<IPluginFactory*(*)()>(dlsym(lib, "GetPluginFactory"));
    if (!entry || !exit || !factory_fn || !entry(lib)) return 2;
    progress("factory");
    IPluginFactory* factory = factory_fn();
    if (!factory) return 3;
    PFactoryInfo factory_info{};
    factory->getFactoryInfo(&factory_info);
    IPluginFactory2* factory2 = nullptr;
    factory->queryInterface(IPluginFactory2::iid, reinterpret_cast<void**>(&factory2));
    const auto count = factory->countClasses();
    if (count < 0 || count > 256) return 4;
    std::ofstream out(argv[2]);
    out << "{\"classes\":[";
    bool comma = false;
    bool processed = false;
    TestHost host;
    for (int32 i=0; i<count; ++i) {
        PClassInfo info{};
        if (factory->getClassInfo(i, &info) != kResultOk) return 5;
        if (std::strncmp(info.category, kVstAudioEffectClass, sizeof(info.category))) continue;
        if (comma) out << ',';
        comma = true;
        out << "{\"id\":\"";
        for (unsigned char c : info.cid) out << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(c);
        PClassInfo2 details{};
        const bool has_details = factory2 && factory2->getClassInfo2(i, &details) == kResultOk;
        const char* vendor = has_details && details.vendor[0] ? details.vendor : factory_info.vendor;
        const size_t vendor_size = has_details && details.vendor[0] ? sizeof(details.vendor) : sizeof(factory_info.vendor);
        out << "\",\"name\":" << quoted(info.name, sizeof(info.name))
            << ",\"vendor\":" << quoted(vendor, vendor_size)
            << ",\"version\":" << quoted(has_details ? details.version : "", has_details ? sizeof(details.version) : 1) << '}';
        if (argc >= 4 && std::string(argv[3]) == "--audio") {
            progress("create-instance");
            IComponent* component = nullptr;
            if (factory->createInstance(info.cid, IComponent::iid, reinterpret_cast<void**>(&component)) != kResultOk || !component) return 6;
            progress("initialize");
            if (component->initialize(&host) != kResultOk) return 7;
            IAudioProcessor* processor = nullptr;
            if (component->queryInterface(IAudioProcessor::iid, reinterpret_cast<void**>(&processor)) != kResultOk || !processor) return 8;
            progress("configure-audio");
            SpeakerArrangement stereo = 3;
            if (processor->setBusArrangements(&stereo,1,&stereo,1) != kResultOk) return 9;
            ProcessSetup setup{}; setup.processMode=kRealtime; setup.symbolicSampleSize=kSample32; setup.maxSamplesPerBlock=128; setup.sampleRate=48000;
            if (processor->setupProcessing(setup) != kResultOk) return 10;
            component->activateBus(kAudio,kInput,0,true); component->activateBus(kAudio,kOutput,0,true);
            progress("activate");
            if (component->setActive(true) != kResultOk || processor->setProcessing(true) != kResultOk) return 11;
            float input[2][128], output[2][128]{};
            float* ins[]={input[0],input[1]}; float* outs[]={output[0],output[1]};
            AudioBusBuffers in{}; in.numChannels=2; in.channelBuffers32=ins;
            AudioBusBuffers ob{}; ob.numChannels=2; ob.channelBuffers32=outs;
            ProcessData data{}; data.numSamples=128; data.numInputs=1; data.numOutputs=1; data.inputs=&in; data.outputs=&ob;
            unsigned blocks = 1000, pace_us = 0;
            if (const auto value = std::getenv("PLUGG_SCAN_BLOCKS")) {
                const auto parsed = std::strtoul(value, nullptr, 10);
                if (parsed > 0 && parsed <= 100000) blocks = parsed;
            }
            if (const auto value = std::getenv("PLUGG_SCAN_PACE_US")) {
                const auto parsed = std::strtoul(value, nullptr, 10);
                if (parsed <= 10000) pace_us = parsed;
            }
            progress("process-audio");
            for(unsigned block=0; block<blocks; ++block) {
                for(int c=0;c<2;++c) for(int s=0;s<128;++s) input[c][s]=static_cast<float>((block+s+c)%127)/127.0f;
                if(processor->process(data)!=kResultOk) return 12;
                for(int c=0;c<2;++c) for(int s=0;s<128;++s) if(std::abs(output[c][s]-input[c][s]*0.5f)>1e-6f) return 13;
                if (pace_us) usleep(pace_us);
            }
            progress("deactivate");
            processor->setProcessing(false); component->setActive(false);
            progress("terminate");
            processor->release(); component->terminate(); component->release();
            processed = true;
        }
    }
    out << "],\"audio_fixture_passed\":" << (processed ? "true" : "false") << "}\n";
    out.close();
    if (const auto hold = std::getenv("PLUGG_SCAN_HOLD_MS")) {
        const auto ms = std::strtoul(hold, nullptr, 10);
        if (ms <= 10000) { progress("hold"); usleep(ms * 1000); }
    }
    progress("release-factory");
    if (factory2) factory2->release();
    factory->release();
    progress("module-exit");
    if (!exit()) return 14;
    progress("unload");
    dlclose(lib);
    progress("complete");
    return comma ? 0 : 15;
}
