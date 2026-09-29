// SPDX-License-Identifier: GPL-3.0-or-later
// Disposable VST2 and CLAP probes, run through the same bridge the DAW loads.
//
// Each writes the same shape as the VST3 probe in scan.cpp: a list of
// classes with an id, a name, a vendor and a version. For VST2 the id is the
// plug-in's four-byte unique ID, which is what a saved project uses to find
// it again; for CLAP it is the plug-in's own id string.
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#include <cmath>
#include <clap/clap.h>
#include <vestige/aeffectx.h>

std::string scan_quoted(const char* text, size_t capacity);

namespace {

// A VST2 plug-in may ask its host things while it opens. The probe answers
// only what a plug-in needs to know it has a VST 2.4 host.
intptr_t VST_CALL_CONV probe_host(AEffect*, int opcode, int, intptr_t, void* data, float) {
    switch (opcode) {
        case audioMasterVersion:
            return 2400;
        case audioMasterGetProductString:
            if (data) std::strcpy(static_cast<char*>(data), "Plugg Test");
            return 1;
        case audioMasterGetSampleRate:
            return 48000;
        case audioMasterGetBlockSize:
            return 128;
        default:
            return 0;
    }
}

std::string vst2_string(AEffect* effect, int opcode) {
    // The specification says 64 bytes at most; some plug-ins write more.
    char text[256]{};
    effect->dispatcher(effect, opcode, 0, 0, text, 0.0f);
    text[sizeof(text) - 1] = 0;
    return text;
}

std::string vst2_id(int32_t unique) {
    std::ostringstream id;
    id << std::hex << std::setw(8) << std::setfill('0') << static_cast<uint32_t>(unique);
    return id.str();
}

// The unique ID as the four characters vendors register, when it is printable.
std::string vst2_code(int32_t unique) {
    std::string code;
    for (int shift = 24; shift >= 0; shift -= 8) {
        const auto c = static_cast<unsigned char>((static_cast<uint32_t>(unique) >> shift) & 0xff);
        if (c < 32 || c >= 127) return "";
        code += static_cast<char>(c);
    }
    return code;
}

// The --audio check, as in scan.cpp: the test gain must halve 1000 blocks.
constexpr unsigned blocks = 1000;
constexpr unsigned frames = 128;

void fill(float (&input)[2][frames], unsigned block) {
    for (int c = 0; c < 2; ++c)
        for (unsigned s = 0; s < frames; ++s) input[c][s] = static_cast<float>((block + s + c) % 127) / 127.0f;
}

bool halved(const float (&input)[2][frames], const float (&output)[2][frames]) {
    for (int c = 0; c < 2; ++c)
        for (unsigned s = 0; s < frames; ++s)
            if (std::abs(output[c][s] - input[c][s] * 0.5f) > 1e-6f) return false;
    return true;
}

bool vst2_audio(AEffect* effect) {
    effect->dispatcher(effect, effSetSampleRate, 0, 0, nullptr, 48000.0f);
    effect->dispatcher(effect, effSetBlockSize, 0, frames, nullptr, 0.0f);
    effect->dispatcher(effect, effMainsChanged, 0, 1, nullptr, 0.0f);
    float input[2][frames], output[2][frames]{};
    float* ins[] = {input[0], input[1]};
    float* outs[] = {output[0], output[1]};
    bool ok = true;
    for (unsigned block = 0; ok && block < blocks; ++block) {
        fill(input, block);
        effect->processReplacing(effect, ins, outs, frames);
        ok = halved(input, output);
    }
    effect->dispatcher(effect, effMainsChanged, 0, 0, nullptr, 0.0f);
    return ok;
}

uint32_t no_events(const clap_input_events_t*) { return 0; }
const clap_event_header_t* no_event(const clap_input_events_t*, uint32_t) { return nullptr; }
bool drop_event(const clap_output_events_t*, const clap_event_header_t*) { return true; }

bool clap_audio(const clap_plugin_factory_t* factory, const char* id) {
    static const clap_host_t host = {
        CLAP_VERSION_INIT, nullptr, "Plugg Test", "Plugg", "", "1",
        [](const clap_host_t*, const char*) -> const void* { return nullptr; },
        [](const clap_host_t*) {}, [](const clap_host_t*) {}, [](const clap_host_t*) {}};
    const clap_plugin_t* plugin = factory->create_plugin(factory, &host, id);
    if (!plugin) return false;
    bool ok = plugin->init(plugin) && plugin->activate(plugin, 48000, frames, frames)
              && plugin->start_processing(plugin);
    float input[2][frames], output[2][frames]{};
    float* ins[] = {input[0], input[1]};
    float* outs[] = {output[0], output[1]};
    clap_audio_buffer_t in{ins, nullptr, 2, 0, 0};
    clap_audio_buffer_t out{outs, nullptr, 2, 0, 0};
    const clap_input_events_t events_in{nullptr, no_events, no_event};
    const clap_output_events_t events_out{nullptr, drop_event};
    for (unsigned block = 0; ok && block < blocks; ++block) {
        fill(input, block);
        clap_process_t process{static_cast<int64_t>(block) * frames, frames, nullptr, &in, &out, 1, 1,
                               &events_in, &events_out};
        ok = plugin->process(plugin, &process) != CLAP_PROCESS_ERROR && halved(input, output);
    }
    plugin->stop_processing(plugin);
    plugin->deactivate(plugin);
    plugin->destroy(plugin);
    return ok;
}

}  // namespace

int scan_vst2(const char* library, const char* output, bool audio) {
    void* lib = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!lib) { std::cerr << dlerror() << '\n'; return 1; }
    using Entry = AEffect* (*)(audioMasterCallback);
    auto entry = reinterpret_cast<Entry>(dlsym(lib, "VSTPluginMain"));
    if (!entry) return 2;
    AEffect* effect = entry(probe_host);
    if (!effect) return 3;
    if (effect->magic != kEffectMagic) return 4;
    effect->dispatcher(effect, effOpen, 0, 0, nullptr, 0.0f);
    const auto category = effect->dispatcher(effect, effGetPlugCategory, 0, 0, nullptr, 0.0f);
    // A shell holds several plug-ins behind one file and needs a host that
    // walks them; the bridge publishes one plug-in per file.
    if (category == kPlugCategShell) {
        effect->dispatcher(effect, effClose, 0, 0, nullptr, 0.0f);
        return 16;
    }
    std::string name = vst2_string(effect, effGetEffectName);
    if (name.empty()) name = vst2_string(effect, effGetProductString);
    const std::string vendor = vst2_string(effect, effGetVendorString);
    const auto version = effect->dispatcher(effect, effGetVendorVersion, 0, 0, nullptr, 0.0f);
    const bool synth = (effect->flags & effFlagsIsSynth) || category == kPlugCategSynth;
    const int32_t unique = effect->uniqueID;
    const bool processed = audio && vst2_audio(effect);
    {
        std::ofstream out(output);
        out << "{\"format\":\"vst2\",\"classes\":[{\"id\":\"" << vst2_id(unique) << '"'
            << ",\"unique_id\":" << unique
            << ",\"code\":" << scan_quoted(vst2_code(unique).c_str(), 4)
            << ",\"name\":" << scan_quoted(name.c_str(), name.size())
            << ",\"vendor\":" << scan_quoted(vendor.c_str(), vendor.size())
            << ",\"version\":\"" << std::dec << version << '"'
            << ",\"instrument\":" << (synth ? "true" : "false")
            << ",\"inputs\":" << effect->numInputs << ",\"outputs\":" << effect->numOutputs
            << "}],\"audio_fixture_passed\":" << (processed ? "true" : "false") << "}\n";
    }
    effect->dispatcher(effect, effClose, 0, 0, nullptr, 0.0f);
    dlclose(lib);
    if (audio && !processed) return 13;
    return unique == 0 ? 17 : 0;
}

int scan_clap(const char* library, const char* output, bool audio) {
    void* lib = dlopen(library, RTLD_NOW | RTLD_LOCAL);
    if (!lib) { std::cerr << dlerror() << '\n'; return 1; }
    auto entry = reinterpret_cast<const clap_plugin_entry_t*>(dlsym(lib, "clap_entry"));
    if (!entry || !entry->init || !entry->get_factory || !entry->deinit) return 2;
    if (!entry->init(library)) return 3;
    auto factory = static_cast<const clap_plugin_factory_t*>(entry->get_factory(CLAP_PLUGIN_FACTORY_ID));
    if (!factory) { entry->deinit(); return 4; }
    const auto count = factory->get_plugin_count(factory);
    if (count > 256) { entry->deinit(); return 4; }
    {
        std::ofstream out(output);
        out << "{\"format\":\"clap\",\"classes\":[";
        bool comma = false;
        bool processed = false;
        for (uint32_t i = 0; i < count; ++i) {
            const auto* descriptor = factory->get_plugin_descriptor(factory, i);
            if (!descriptor || !descriptor->id || !descriptor->id[0]) continue;
            if (comma) out << ',';
            comma = true;
            const auto text = [](const char* value) { return value ? value : ""; };
            out << "{\"id\":" << scan_quoted(descriptor->id, std::strlen(descriptor->id))
                << ",\"name\":" << scan_quoted(text(descriptor->name), std::strlen(text(descriptor->name)))
                << ",\"vendor\":" << scan_quoted(text(descriptor->vendor), std::strlen(text(descriptor->vendor)))
                << ",\"version\":" << scan_quoted(text(descriptor->version), std::strlen(text(descriptor->version)))
                << ",\"features\":[";
            for (size_t f = 0; descriptor->features && descriptor->features[f] && f < 64; ++f)
                out << (f ? "," : "") << scan_quoted(descriptor->features[f], std::strlen(descriptor->features[f]));
            out << "]}";
            if (audio && !(processed = clap_audio(factory, descriptor->id))) { out.close(); entry->deinit(); return 13; }
        }
        out << "],\"audio_fixture_passed\":" << (processed ? "true" : "false") << "}\n";
        if (!comma) { out.close(); entry->deinit(); return 15; }
    }
    entry->deinit();
    dlclose(lib);
    return 0;
}
