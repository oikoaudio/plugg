/* SPDX-License-Identifier: GPL-3.0-or-later
 * Minimal freestanding Windows CLAP fixture: halves its input, like gain.cpp.
 * Built against the CLAP headers yabridge vendors. Not a product plug-in. */
#include <clap/clap.h>

void* memset(void* d, int c, size_t n) {for (size_t i = 0; i < n; ++i) ((char*)d)[i] = (char)c; return d;}
int _fltused = 0;

static const char* const features[] = {CLAP_PLUGIN_FEATURE_AUDIO_EFFECT, CLAP_PLUGIN_FEATURE_STEREO, NULL};
static const clap_plugin_descriptor_t descriptor = {
    .clap_version = CLAP_VERSION_INIT,
    .id = "org.plugg.test.gain",
    .name = "Plugg Test Gain CLAP",
    .vendor = "Plugg Tests",
    .url = "",
    .manual_url = "",
    .support_url = "",
    .version = "1.0.0",
    .description = "Halves its input.",
    .features = features,
};

static uint32_t port_count(const clap_plugin_t* plugin, bool input) {(void)plugin; (void)input; return 1;}
static bool port_info(const clap_plugin_t* plugin, uint32_t index, bool input, clap_audio_port_info_t* info) {
    (void)plugin; (void)input;
    if (index) return false;
    memset(info, 0, sizeof(*info));
    info->id = 0;
    info->name[0] = 'M'; info->name[1] = 'a'; info->name[2] = 'i'; info->name[3] = 'n';
    info->channel_count = 2;
    info->flags = CLAP_AUDIO_PORT_IS_MAIN;
    info->port_type = CLAP_PORT_STEREO;
    info->in_place_pair = CLAP_INVALID_ID;
    return true;
}
static const clap_plugin_audio_ports_t audio_ports = {.count = port_count, .get = port_info};

static bool init(const clap_plugin_t* plugin) {(void)plugin; return true;}
static void destroy(const clap_plugin_t* plugin) {(void)plugin;}
static bool activate(const clap_plugin_t* plugin, double rate, uint32_t min, uint32_t max) {
    (void)plugin; (void)rate; (void)min; (void)max; return true;
}
static void deactivate(const clap_plugin_t* plugin) {(void)plugin;}
static bool start_processing(const clap_plugin_t* plugin) {(void)plugin; return true;}
static void stop_processing(const clap_plugin_t* plugin) {(void)plugin;}
static void reset(const clap_plugin_t* plugin) {(void)plugin;}
static clap_process_status process(const clap_plugin_t* plugin, const clap_process_t* data) {
    (void)plugin;
    if (data->audio_inputs_count < 1 || data->audio_outputs_count < 1) return CLAP_PROCESS_ERROR;
    for (uint32_t c = 0; c < 2; ++c)
        for (uint32_t s = 0; s < data->frames_count; ++s)
            data->audio_outputs[0].data32[c][s] = data->audio_inputs[0].data32[c][s] * 0.5f;
    return CLAP_PROCESS_CONTINUE;
}
static const void* get_extension(const clap_plugin_t* plugin, const char* id) {
    (void)plugin;
    const char* want = CLAP_EXT_AUDIO_PORTS;
    size_t i = 0;
    while (id[i] && id[i] == want[i]) ++i;
    return id[i] == want[i] ? &audio_ports : NULL;
}
static void on_main_thread(const clap_plugin_t* plugin) {(void)plugin;}

static clap_plugin_t pool[16];
static uint32_t used = 0;

static uint32_t count(const clap_plugin_factory_t* factory) {(void)factory; return 1;}
static const clap_plugin_descriptor_t* describe(const clap_plugin_factory_t* factory, uint32_t index) {
    (void)factory; return index ? NULL : &descriptor;
}
static const clap_plugin_t* create(const clap_plugin_factory_t* factory, const clap_host_t* host, const char* id) {
    (void)factory; (void)host;
    const char* want = descriptor.id;
    size_t i = 0;
    while (id[i] && id[i] == want[i]) ++i;
    if (id[i] != want[i] || used == 16) return NULL;
    clap_plugin_t* plugin = &pool[used++];
    plugin->desc = &descriptor;
    plugin->plugin_data = NULL;
    plugin->init = init;
    plugin->destroy = destroy;
    plugin->activate = activate;
    plugin->deactivate = deactivate;
    plugin->start_processing = start_processing;
    plugin->stop_processing = stop_processing;
    plugin->reset = reset;
    plugin->process = process;
    plugin->get_extension = get_extension;
    plugin->on_main_thread = on_main_thread;
    return plugin;
}
static const clap_plugin_factory_t factory = {.get_plugin_count = count, .get_plugin_descriptor = describe,
                                              .create_plugin = create};

static bool entry_init(const char* path) {(void)path; return true;}
static void entry_deinit(void) {}
static const void* entry_factory(const char* id) {
    const char* want = CLAP_PLUGIN_FACTORY_ID;
    size_t i = 0;
    while (id[i] && id[i] == want[i]) ++i;
    return id[i] == want[i] ? &factory : NULL;
}
__declspec(dllexport) const clap_plugin_entry_t clap_entry = {
    .clap_version = CLAP_VERSION_INIT, .init = entry_init, .deinit = entry_deinit, .get_factory = entry_factory};

int DllMain(void* module, unsigned reason, void* reserved) {(void)module; (void)reason; (void)reserved; return 1;}
