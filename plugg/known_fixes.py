"""What is already known about something someone adds, said when they add it.

Most questions about a new installer have been answered somewhere: by one of
Plugg's own recipes, by the vendor notes behind Help, or in the research other
projects publish, which Plugg keeps as leads. This gathers those answers for
one installer or plug-in file, so the person sees them while installing, and
first when something goes wrong, instead of having to know where to look.

Every answer says where it comes from. A lead is someone else's research on a
different Wine setup: it is a hint, never a claim that something works here.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import re

from . import help_content, leads

#: Words in an installer's file name that say nothing about the product.
NOISE = {'setup', 'installer', 'install', 'win', 'windows', 'win64', 'x64', 'x86', 'vst3', 'vst', 'full',
         'exe', 'msi', 'mac', 'pc', 'the', 'and', 'by', 'plugin', 'plugins', 'demo', 'trial'}


def _words(text):
    words = re.findall(r'[a-z]+', (text or '').casefold())
    return {w for w in words if w not in NOISE and len(w) > 1}


def hints(setup):
    """Another project's setup for a product, in the words Plugg uses for the same things."""
    said = []
    if setup.get('dxvk'):
        said.append('DXVK graphics')
    if setup.get('winetricks'):
        said.append('Microsoft components: ' + ', '.join(setup['winetricks']))
    if setup.get('virtual_desktop'):
        said.append('a Wine virtual desktop')
    if setup.get('env'):
        said.append('environment settings: ' + ', '.join(sorted(setup['env'])))
    return said


def vendor_of(path):
    """The maker named in a Windows file's own version information, if it has one."""
    if not path:
        return None
    from . import pe_version
    company = pe_version.version_info(path).get('CompanyName')
    if not company:
        return None
    from .vendors import vendor_name
    return vendor_name(company)


def lookup(path=None, sha256=None, vendor=None, known_modules=None, files=None):
    """[{'kind', 'text', 'source'}] for an installer or plug-in file, most specific first.

    `known_modules` is the standalone catalogue's modules by hash, when the
    caller has it. `files` replaces the bundled leads, for tests.
    """
    found = []
    name = Path(path).stem if path else ''
    vendor = vendor or vendor_of(path)

    if sha256 and known_modules and sha256 in known_modules:
        module = known_modules[sha256]
        found.append({'kind': 'recipe', 'source': 'Plugg',
                      'text': 'Plugg has a tested setup for this exact file'
                              + (' (' + module['vendor'] + ')' if module.get('vendor') else '') + '.'})
    if sha256:
        from . import recipes
        try:
            if recipes.recognized(sha256):
                found.append({'kind': 'recipe', 'source': 'Plugg',
                              'text': 'Plugg has a tested setup recipe for this installer (Klevgrand).'})
        except (OSError, ValueError, KeyError):
            pass

    note = help_content.vendor_note(vendor) if vendor else None
    if note:
        known_as, (status, text) = note
        found.append({'kind': status, 'source': 'Plugg',
                      'text': '%s: %s. %s' % (known_as, status, text)})

    exact = leads.for_file(sha256, files) if sha256 else []
    for product in exact:
        setup = hints(product.get('cabinet') or {})
        found.append({'kind': 'lead', 'source': leads.attribution(product),
                      'text': "Another project's catalogue knows this exact file (%s)." % product['name']
                              + (' It ran there with ' + '; '.join(setup) + '.' if setup else '')})

    if vendor:
        mine = _words(name)
        for product in leads.native(leads.for_vendor(vendor, files)):
            if mine and _words(product['name']) and _words(product['name']) <= mine:
                found.append({'kind': 'native', 'source': leads.attribution(product),
                              'text': '%s has a native Linux version. It will work better in your DAW '
                                      'than the Windows one.' % product['name']})
        if not exact:
            windows = [p for p in leads.for_vendor(vendor, files) if p['kind'] == 'windows']
            matched = [p for p in windows if mine and _words(p['name']) and _words(p['name']) <= mine]
            for product in matched[:1]:
                setup = hints(product.get('cabinet') or {})
                if setup:
                    found.append({'kind': 'lead', 'source': leads.attribution(product),
                                  'text': '%s ran in another project with %s. A hint, not tested here.'
                                          % (product['name'], '; '.join(setup))})
    return found


def summary(found, limit=2):
    """The one or two lines worth showing while something installs."""
    order = {'native': 0, 'recipe': 1, 'known problem': 2, 'tested': 3, 'experimental': 4, 'lead': 5}
    return [item['text'] for item in sorted(found, key=lambda i: order.get(i['kind'], 9))[:limit]]
