"""The plug-in formats Plugg publishes, and how each one is laid out.

yabridge bridges VST3, VST2 and CLAP, and each needs its own native files
and its own folder for the DAW to scan. Which of them a library publishes
is the person's choice, kept in settings.json: VST3 by default, since that
is what every tested DAW loads. VST2 is for projects made on Windows that
saved their plug-ins as VST2; CLAP for DAWs that prefer it. When a format
is on, it is published for every plug-in that ships it, whether or not the
same plug-in also has another format.

A publication is always one link in the DAW's folder to a complete directory
in the library, so it appears or disappears in one step:

- VST3: `~/.vst3/plugg/Name.vst3` -> `bundles/Name.vst3`, a VST3 bundle.
- VST2: `~/.vst/plugg/Name` -> `bundles/vst2/Name`, holding `Name.so` and `Name.dll`.
- CLAP: `~/.clap/plugg/Name` -> `bundles/clap/Name`, holding `Name.clap` and `Name.clap-win`.

VST2 and CLAP publish a directory rather than the file itself because the
patched chainloader looks for `.plugg-managed` beside the path the DAW
loaded it from, without resolving links. The Windows file sits beside the
native one under the name yabridge looks for: CLAP's `.clap-win` keeps a
Windows `.clap` out of the DAW's own scan.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
import shutil
from pathlib import Path

FORMATS = ('vst3', 'vst2', 'clap')
DEFAULT = ('vst3',)
LABELS = {'vst3': 'VST3', 'vst2': 'VST2', 'clap': 'CLAP'}
#: settings.json keys: the formats published, and where the non-VST3 ones go.
SETTING = 'publish_formats'
FOLDERS_SETTING = 'publication_folders'

PLUGIN_LIBRARY = {'vst3': 'libyabridge-vst3.so', 'vst2': 'libyabridge-vst2.so', 'clap': 'libyabridge-clap.so'}
CHAINLOADER = {'vst3': 'libyabridge-chainloader-vst3.so', 'vst2': 'libyabridge-chainloader-vst2.so',
               'clap': 'libyabridge-chainloader-clap.so'}
HOST = ('yabridge-host.exe', 'yabridge-host.exe.so')
#: The host yabridge starts for a 32-bit VST2 plug-in, found beside the plug-in library.
HOST_32 = ('yabridge-host-32.exe', 'yabridge-host-32.exe.so')
#: PE machine numbers.
X86_64, I386 = 0x8664, 0x14C
#: The file a DAW loads, by format.
NATIVE_SUFFIX = {'vst3': '.so', 'vst2': '.so', 'clap': '.clap'}
#: The Windows module beside it, named as yabridge looks for it.
WINDOWS_SUFFIX = {'vst3': '.vst3', 'vst2': '.dll', 'clap': '.clap-win'}
#: What the Windows module exports, which is how a VST2 DLL is told from any other DLL.
VST2_ENTRY_POINTS = {'VSTPluginMain', 'main'}
CLAP_ENTRY_POINT = 'clap_entry'
#: Where a plug-in dropped on the window is installed, inside its environment.
IMPORT_FOLDER = {'vst3': 'Program Files/Common Files/VST3', 'vst2': 'Program Files/Common Files/VST2',
                 'clap': 'Program Files/Common Files/CLAP'}
#: The file extensions a plug-in can be dropped as.
IMPORT_SUFFIXES = {'.vst3': 'vst3', '.dll': 'vst2', '.clap': 'clap'}


class FormatError(ValueError):
    pass


def of(metadata):
    """The format a publication's metadata records; older records are all VST3."""
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    value = (metadata or {}).get('format', 'vst3')
    if value not in FORMATS:
        raise FormatError('Unknown plug-in format: ' + str(value))
    return value


def module_format(path):
    """The format of an installed Windows module, or None for anything else.

    Only the file's own name and headers decide: a `.vst3` file is what its
    extension says, a `.clap` file must export `clap_entry`, and a `.dll` is
    a VST2 plug-in only when it exports a VST2 entry point. Nothing is loaded.
    """
    from . import pe_version
    suffix = Path(path).suffix.lower()
    if suffix == '.vst3':
        return 'vst3'
    if suffix == '.clap' and CLAP_ENTRY_POINT in pe_version.exports(path):
        return 'clap'
    if suffix == '.dll' and pe_version.exports(path) & VST2_ENTRY_POINTS:
        return 'vst2'
    return None


def is_import(job):
    """A job for a plug-in dropped on the window, rather than an installer: its kind is the format."""
    return job.get('kind') in FORMATS


def _settings(root):
    path = Path(root) / 'settings.json'
    return json.loads(path.read_text()) if path.is_file() else {}


def enabled(root):
    """The formats this library publishes, in FORMATS order."""
    chosen = _settings(root).get(SETTING)
    if not isinstance(chosen, list):
        return DEFAULT
    return tuple(name for name in FORMATS if name in chosen) or DEFAULT


def default_folder(publication, name):
    """Where a format is published when nobody has said: beside the VST3 folder.

    `~/.vst3/plugg` becomes `~/.vst/plugg` and `~/.clap/plugg`, the folders
    DAWs look in. A library published somewhere else, such as a development
    library, gets folders next to its own, never the person's real ones.
    """
    publication = Path(publication)
    if name == 'vst3':
        return publication
    parts = publication.parts
    if '.vst3' in parts:
        index = len(parts) - 1 - parts[::-1].index('.vst3')
        return Path(*parts[:index], {'vst2': '.vst', 'clap': '.clap'}[name], *parts[index + 1:])
    return publication.with_name(publication.name + '-' + name)


def folder(store, name):
    """The folder the DAW scans for this format in this library."""
    if name == 'vst3':
        return store.publication
    recorded = _settings(store.root).get(FOLDERS_SETTING, {})
    if isinstance(recorded, dict) and recorded.get(name):
        return Path(recorded[name])
    return default_folder(store.publication, name)


def choose(store, chosen):
    """Record which formats to publish. VST3 cannot be switched off.

    Every VST3 publication, and every environment and recipe, assumes it;
    the choice is which formats to add. The folders are recorded the first
    time a format is switched on, so they do not move if the default does.
    Returns what changed, so the caller can say what to do next.
    """
    from .core import atomic_json, lock
    chosen = set(chosen)
    unknown = chosen - set(FORMATS)
    if unknown:
        raise FormatError('Unknown plug-in format: ' + ', '.join(sorted(unknown))
                          + '. Choose from ' + ', '.join(LABELS[x] for x in FORMATS) + '.')
    chosen.add('vst3')
    with lock(Path(store.root) / 'publication.lock'):
        settings = _settings(store.root)
        before = enabled(store.root)
        after = tuple(name for name in FORMATS if name in chosen)
        folders = settings.get(FOLDERS_SETTING)
        folders = dict(folders) if isinstance(folders, dict) else {}
        for name in after:
            if name != 'vst3' and not folders.get(name):
                folders[name] = str(default_folder(store.publication, name))
        settings[SETTING] = list(after)
        if folders:
            settings[FOLDERS_SETTING] = folders
        atomic_json(Path(store.root) / 'settings.json', settings)
    return {'formats': list(after), 'added': [x for x in after if x not in before],
            'removed': [x for x in before if x not in after],
            'folders': {name: str(folder(store, name)) for name in after}}


def bundles(store, name):
    """Where the library keeps complete bundles of this format."""
    root = Path(store.root) / 'bundles'
    return root if name == 'vst3' else root / name


def publication_name(name, readable):
    """The DAW-facing name of a publication: a VST3 bundle carries its suffix."""
    return readable + '.vst3' if name == 'vst3' else readable


def readable(path, name):
    """The readable name a publication was made under, without its format's suffix."""
    path = Path(path)
    return path.name[:-len('.vst3')] if name == 'vst3' and path.name.endswith('.vst3') else path.name


def native_directory(bundle, name):
    """The directory holding the files the DAW loads, and the managed marker."""
    return Path(bundle) / 'Contents/x86_64-linux' if name == 'vst3' else Path(bundle)


def loader(bundle, name):
    """The chainloader copy the DAW loads."""
    bundle = Path(bundle)
    return native_directory(bundle, name) / (readable(bundle, name) + NATIVE_SUFFIX[name])


def windows_link(bundle, name):
    """The link to the Windows module, where yabridge looks for it."""
    bundle = Path(bundle)
    if name == 'vst3':
        return bundle / 'Contents/x86_64-win' / bundle.name
    return bundle / (bundle.name + WINDOWS_SUFFIX[name])


def bridge_links(name, bitbridge=False):
    """The bridge files a bundle links to rather than copies.

    A bundle for a 32-bit VST2 plug-in also links the 32-bit host.
    """
    return (PLUGIN_LIBRARY[name],) + HOST + (HOST_32 if bitbridge else ())


def links_in(native, name):
    """The bridge files an existing bundle's native directory links to."""
    return bridge_links(name, (Path(native) / HOST_32[0]).is_symlink())


def is_32_bit(module):
    """Whether a Windows module is 32-bit. Unreadable counts as not."""
    from .core import HostError, pe_machine
    try:
        return pe_machine(module) == I386
    except (HostError, OSError):
        return False


def make_bundle(bridge, module, dest, name):
    """Build a complete bundle for one Windows module in dest, linking the bridge release."""
    dest = Path(dest)
    native = native_directory(dest, name)
    native.mkdir(parents=True)
    # The DLL and Linux proxy need corresponding basenames.
    shutil.copy2(Path(bridge) / CHAINLOADER[name], loader(dest, name))
    (native / '.plugg-managed').write_text('1\n')
    bitbridge = name == 'vst2' and is_32_bit(module)
    if bitbridge and not all((Path(bridge) / item).is_file() for item in HOST_32):
        raise FormatError('This bridge build has no 32-bit host, so it cannot load a 32-bit plug-in.')
    for item in bridge_links(name, bitbridge):
        (native / item).symlink_to(Path(bridge) / item)
    windows = windows_link(dest, name)
    windows.parent.mkdir(exist_ok=True)
    windows.symlink_to(module)
    if name == 'vst3' and module.parent.name == 'x86_64-win' and module.parent.parent.name == 'Contents':
        resources = module.parent.parent / 'Resources'
        if resources.is_dir():
            (dest / 'Contents/Resources').symlink_to(resources)
    # Do not copy moduleinfo.json: Windows and Linux class-ID byte order differs.
    return loader(dest, name)


def supported_by(bridge):
    """The formats a bridge release can publish: older releases carry VST3 only."""
    bridge = Path(bridge)
    return tuple(name for name in FORMATS
                 if all((bridge / item).is_file() for item in (CHAINLOADER[name], PLUGIN_LIBRARY[name])))


def apply(store, chosen):
    """Choose the formats Plugg publishes from now on.

    The choice is additive, like ticking a box on the next installer: it
    decides what new installations and checks publish, and never removes a
    plug-in already published. Switching VST2 off must not break the old
    project that needed it. Taking plug-ins out of the DAW stays what forget
    does, one explicit step at a time.

    A format switched on publishes nothing by itself either: plug-ins are
    loaded to be checked, and loading an unactivated plug-in can open its
    activation window, so that waits for Check again on each vendor.
    """
    bridge = store.bridge_directory()
    if (bridge / 'build.json').is_file():
        missing = [name for name in chosen if name in FORMATS and name not in supported_by(bridge)]
        if missing:
            raise FormatError('The bridge build at ' + str(bridge) + ' cannot publish '
                              + ' or '.join(LABELS[x] for x in missing)
                              + '. Update Plugg, or rebuild the bridge with scripts/build-bridge.sh.')
    return choose(store, chosen)


def spoken(names):
    """"VST2", "VST2 and CLAP", "VST3, VST2 and CLAP"."""
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def summary(store):
    """One sentence on what the current choice means, for the settings window and the CLI."""
    chosen = [LABELS[name] for name in enabled(store.root)]
    extra = chosen[1:]
    if not extra:
        return 'New plug-ins are published as VST3 only.'
    return ('New plug-ins are published as ' + spoken(chosen) + '. For plug-ins you already have, use Check again '
            'or Refresh library on their vendor to add ' + spoken(extra) + '. Switching a format off later stops '
            'new ones; it never removes what is already in your DAW.')
