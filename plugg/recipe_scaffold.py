"""Write a valid starting recipe from a file the contributor actually has.

Most of what stops someone contributing a recipe is not judgement, it is
transcription: the exact SHA-256 of a bundle, the right dependency reference,
which fields a kind of recipe needs. That is all derivable from the file, so
the tool does it and the person is left with the part only they can supply —
what they tested, and what worked.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import re

from . import core

#: The component a plug-in most often needs, and the one to start from.
DEFAULT_DEPENDENCY = 'plugg.vc2022-x64@1'
DEFAULT_GRAPHICS = 'plugg.graphics-dxvk@1'


def suggest_id(vendor):
    """A namespaced id from a vendor name, in the namespace a contributor owns."""
    slug = re.sub(r'[^a-z0-9]+', '-', vendor.casefold()).strip('-')
    return 'local.' + (slug or 'vendor')


def quote(text):
    """TOML basic string. Recipes carry no control characters, so this is enough."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def scaffold(source, *, identity=None, vendor=None, dependency=DEFAULT_DEPENDENCY):
    """Build a recipe skeleton for a Windows VST3 or installer the user has."""
    from . import standalone
    source = Path(source).expanduser().absolute()
    if not source.exists():
        raise core.HostError('No such file: ' + str(source))
    if source.is_symlink():
        raise core.HostError('Choose the original file, not a link.')
    kind = 'helper' if source.suffix.lower() in ('.exe', '.msi') else 'modules'
    vendor = (vendor or source.stem).strip()
    identity = identity or suggest_id(vendor)
    if kind == 'helper':
        core.installer_type(source)
        text = _helper(source, identity, vendor)
    else:
        text = _modules(source, identity, vendor, dependency, standalone)
    return text + _lead_notes(source, vendor)


def _lead_notes(source, vendor):
    """What published research already knows about this vendor, as comments."""
    from . import leads
    exact = leads.for_file(core.digest(source)) if source.is_file() else []
    found = {product['id']: product for product in [*exact, *leads.for_vendor(vendor)]}
    lines = leads.scaffold_comment(list(found.values()))
    return '\n'.join(lines) + '\n' if lines else ''


def _modules(source, identity, vendor, dependency, standalone):
    module = standalone.module_path(source)
    fingerprint = core.digest(module)
    return '\n'.join([
        '# A direct-import recipe: it recognizes an exact plug-in file you already',
        '# have and installs it with the runtime it needs. Nothing is downloaded',
        '# except the pinned Microsoft component named below.',
        '#',
        '# Before opening a pull request:',
        '#   plugg recipe validate this-file.toml',
        '#   plugg recipe explain this-file.toml',
        '',
        'schema = 1',
        'id = ' + quote(identity),
        'revision = 1',
        'kind = "vendor"',
        'name = ' + quote(vendor + ' direct VST3 imports'),
        'vendor = ' + quote(vendor),
        'requires = [' + quote(DEFAULT_GRAPHICS) + ', ' + quote(dependency) + ']',
        '# Say what you tested: product versions, DAW, and what you observed for',
        '# installation, audio, the editor, reopening and project recall.',
        'notes = "TODO: what was tested, on what, and what was observed."',
        '',
        '# The exact file this recipe recognizes. Computed from ' + module.name + '.',
        '[modules.' + quote(fingerprint) + ']',
        'name = ' + quote(module.stem),
        '# Which runtime this plug-in needs. Run "recipe components" to see the',
        '# alternatives and what each one solves.',
        'dependency = ' + quote(dependency),
        '',
    ])


def _helper(source, identity, vendor):
    fingerprint = core.digest(source)
    return '\n'.join([
        '# A helper recipe: it recognizes an exact vendor installer and runs it in a',
        '# fresh environment. This asks to run a Windows installer with arguments',
        '# this file chooses, so it is a reviewed-tier capability: it cannot live in',
        '# recipes/community/. Open the pull request anyway and say what you tested.',
        '#',
        '# Arguments may not name another drive letter, a network path, a parent',
        '# directory or a Windows variable. Use the vendor\'s documented silent',
        '# install switches and nothing else.',
        '#',
        '# Before opening a pull request:',
        '#   plugg recipe validate this-file.toml',
        '#   plugg recipe explain this-file.toml',
        '',
        'schema = 1',
        'id = ' + quote(identity),
        'revision = 1',
        'kind = "vendor"',
        'name = ' + quote(vendor + ' setup'),
        'vendor = ' + quote(vendor),
        'requires = [' + quote(DEFAULT_GRAPHICS) + ']',
        'notes = "TODO: what was tested, on what, and what was observed."',
        '',
        '[helper]',
        '# The exact installer, computed from ' + source.name + '.',
        'installer_sha256 = ' + quote(fingerprint),
        '# The vendor\'s silent-install switches. Empty means the installer opens',
        '# its own window, which is often what you want for a login step.',
        'arguments = []',
        'name = ' + quote(vendor + ' Helper'),
        '# Where the installer puts the application, relative to drive C.',
        'executable = "TODO/Vendor/Helper.exe"',
        '# True if the installer needs the pinned archive utilities present.',
        'archive_tools = false',
        '',
    ])
