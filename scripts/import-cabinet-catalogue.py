#!/usr/bin/env python3
"""Import Cabinet's plug-in catalogue as recipe leads.

Cabinet (https://github.com/Mark12870/cabinet, GPL-3.0-or-later) keeps a
curated library of Windows and native Linux plug-ins: download locations,
pinned hashes, silent-install switches, and the Wine settings each needed on
its maintainer's machines. That is exactly the research a recipe author needs
before writing a recipe here, so this script converts it into data files under
plugg/leads/cabinet/ with the source commit recorded.

A lead is reference material, not a recipe: nothing in it is executed, and
nothing in it has been tested with this project's runtime.

    python3 scripts/import-cabinet-catalogue.py /path/to/cabinet

Artwork is not imported; its provenance varies (see Cabinet's SOURCES.md).
Held-back entries are imported with the reason Cabinet gives.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import argparse
import re
import subprocess
import sys

REPOSITORY = 'https://github.com/Mark12870/cabinet'
OUTPUT = Path(__file__).resolve().parent.parent / 'plugg' / 'leads' / 'cabinet'
LISTS = {'Formats', 'Winetricks'}
LINES = {'LaunchArgs', 'Env'}
PROSE = {'Description', 'Licensing'}
RENAMED = {
    'Name': 'name', 'Kind': 'kind', 'Category': 'category', 'Summary': 'summary', 'Developer': 'developer',
    'Version': 'version', 'Licence': 'licence', 'Licensing': 'licensing', 'Formats': 'formats',
    'Homepage': 'homepage', 'Account': 'account', 'Description': 'description',
}
DOWNLOAD = {'Source': 'source', 'Url': 'url', 'Sha256': 'sha256', 'DemoUrl': 'demo_url', 'DemoSha256': 'demo_sha256'}
SETUP = {
    'Prefix': 'prefix', 'Runner': 'runner', 'Dxvk': 'dxvk', 'Sync': 'sync', 'Winetricks': 'winetricks',
    'Env': 'env', 'Desktop': 'virtual_desktop', 'Launch': 'launch', 'LaunchArgs': 'launch_args',
    'LaunchHelper': 'launch_helper', 'LaunchService': 'launch_service', 'Scheme': 'url_scheme', 'Keep': 'keep',
    'Data': 'data', 'Relink': 'relink', 'Script': 'script', 'Recover': 'recover_script',
}
TEXT_SUPPORT = {'.iss', '.reg', '.ini', '.txt', '.cfg', '.json'}
MAC = re.compile(r'\b[0-9a-f]{2}(?:[-:][0-9a-f]{2}){5}\b', re.I)


def fields(text):
    """Cabinet's entry format: `Key: value`, or `Key:` followed by an indented block."""
    result, block, lines = {}, None, []

    def close():
        nonlocal block
        if block is not None:
            result[block] = '\n'.join(lines).strip()
            lines.clear()
            block = None

    for raw in text.split('\n'):
        line = raw.strip()
        if block is not None and (not line or raw[0].isspace()):
            lines.append(line)
            continue
        close()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition(':')
        if not separator or not re.fullmatch(r'[A-Z][A-Za-z0-9]*', key):
            raise ValueError('Unrecognised line: ' + raw)
        if value.strip():
            result[key] = value.strip()
        else:
            block = key
    close()
    return result


def prose(text):
    return '\n\n'.join(' '.join(part.split()) for part in re.split(r'\n\s*\n', text) if part.strip())


def value(key, text):
    if key in LISTS:
        return [item.strip() for item in text.split(',') if item.strip()]
    if key in LINES:
        return [line for line in text.split('\n') if line.strip()]
    if key in PROSE:
        return prose(text)
    if key in ('Dxvk', 'Desktop'):
        if text not in ('true', 'false'):
            raise ValueError(key + ' must be true or false')
        return text == 'true'
    return text


def quote(text):
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
    if any(ord(character) < 32 for character in escaped):
        raise ValueError('Control character in ' + repr(text))
    return '"' + escaped + '"'


def literal(text):
    if "'''" in text:
        return quote(text)
    return "'''\n" + text.rstrip('\n') + "\n'''"


def render(item):
    if isinstance(item, bool):
        return 'true' if item else 'false'
    if isinstance(item, list):
        return '[' + ', '.join(quote(entry) for entry in item) + ']'
    return quote(item)


def held_back(directory):
    notes = sorted(directory.glob('*.md'))
    if not notes:
        return None
    text = notes[0].read_text()
    paragraphs = [part for part in re.split(r'\n\s*\n', text) if part.strip() and not part.lstrip().startswith('#')]
    reason = prose(paragraphs[0]).replace('**', '') if paragraphs else 'Held back by Cabinet.'
    return MAC.sub('<redacted>', reason), notes[0].name


def vendor_file(directory, commit):
    entries = []
    for path in sorted(directory.glob('*.yml')):
        data = fields(path.read_text())
        unknown = set(data) - set(RENAMED) - set(DOWNLOAD) - set(SETUP)
        if unknown:
            raise ValueError(str(path) + ': fields this importer does not understand: ' + ', '.join(sorted(unknown)))
        entries.append((path.stem, data))
    if not entries:
        return None
    developers = {data.get('Developer', '') for _, data in entries} - {''}
    vendor = sorted(developers)[0] if len(developers) == 1 else directory.name
    scripts = sorted({data[key] for _, data in entries for key in ('Script', 'Recover') if key in data})
    lines = [
        '# Recipe leads imported from Cabinet, ' + REPOSITORY,
        '# Source: data/library/' + directory.name + ' at ' + commit,
        '# Cabinet is GPL-3.0-or-later; this derived data is distributed under the same licence.',
        '# Generated by scripts/import-cabinet-catalogue.py. Regenerate rather than editing by hand.',
        '#',
        '# A lead is research, not a recipe: nothing here is executed, and none of it has been',
        '# tested with this project. Cabinet runs plain Wine runners; this project uses a',
        '# pinned UMU-Proton runtime, so runner names and settings are hints only.',
        '',
        'schema = 1',
        'source = "cabinet"',
        'source_url = ' + quote(REPOSITORY),
        'source_commit = ' + quote(commit),
        'source_path = ' + quote('data/library/' + directory.name),
        'licence = "GPL-3.0-or-later"',
        'vendor = ' + quote(vendor),
    ]
    held = held_back(directory)
    if held:
        lines += ['held_back = true', 'held_back_reason = ' + quote(held[0]),
                  'held_back_note = ' + quote(held[1])]
    for identity, data in entries:
        lines += ['', '[[products]]', 'id = ' + quote(identity)]
        for key, name in RENAMED.items():
            if key in data:
                lines.append(name + ' = ' + render(value(key, data[key])))
        download = [(name, data[key]) for key, name in DOWNLOAD.items() if key in data]
        if download:
            lines += ['', '[products.download]'] + [name + ' = ' + render(text) for name, text in download]
        setup = [(name, value(key, data[key])) for key, name in SETUP.items() if key in data]
        if setup:
            lines += ['', '[products.cabinet]'] + [name + ' = ' + render(item) for name, item in setup]
    support = sorted(path for path in directory.iterdir()
                     if path.is_file() and path.suffix.lower() in TEXT_SUPPORT)
    if support:
        lines += ['', '# Files Cabinet\'s scripts read, such as an InstallShield response file. Reference only.',
                  '[reference_files]']
        for path in support:
            lines.append(quote(path.name) + ' = ' + literal(path.read_text().replace('\r\n', '\n')))
    if scripts:
        lines += ['', '# Cabinet\'s install scripts, kept verbatim as reference. They are shell scripts',
                  '# for Cabinet\'s own environment ($WINE, $CABINET_PREFIX, ...) and are never run here.',
                  '[reference_scripts]']
        for script in scripts:
            lines.append(quote(script) + ' = ' + literal((directory / script).read_text()))
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('cabinet', type=Path, help='A Cabinet checkout')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    library = args.cabinet / 'data' / 'library'
    if not library.is_dir():
        sys.exit('No data/library in ' + str(args.cabinet))
    commit = subprocess.run(['git', '-C', str(args.cabinet), 'rev-parse', 'HEAD'],
                            check=True, capture_output=True, text=True).stdout.strip()
    args.output.mkdir(parents=True, exist_ok=True)
    for stale in args.output.glob('*.toml'):
        stale.unlink()
    written = 0
    for directory in sorted(path for path in library.iterdir() if path.is_dir()):
        text = vendor_file(directory, commit)
        if text:
            (args.output / (directory.name + '.toml')).write_text(text)
            written += 1
    print('Wrote ' + str(written) + ' vendor files from Cabinet ' + commit[:12] + ' to ' + str(args.output))


if __name__ == '__main__':
    main()
