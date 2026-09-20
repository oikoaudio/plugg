"""Recipe leads: research other projects have published, for recipe authors.

A lead says where a vendor's installer comes from, what hash it had, which
switches install it silently and what another project needed to make it run.
It is not a recipe. Nothing in a lead is executed, and a lead never marks a
plug-in as compatible here.

The bundled leads come from Cabinet (https://github.com/Mark12870/cabinet,
GPL-3.0-or-later), converted by scripts/import-cabinet-catalogue.py with the
source commit recorded in every file.

A lead also answers a question the recipe path cannot: whether a product has
a native Linux build. Bridging one of those gives worse latency and a worse
editor for nothing, so `recipe init` says so before anyone writes a recipe.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import re
import tomllib

DIRECTORY = Path(__file__).resolve().parent / 'leads'
SHA256 = re.compile(r'[0-9a-f]{64}')
TOP = {'schema', 'source', 'source_url', 'source_commit', 'source_path', 'licence', 'vendor', 'products',
       'reference_scripts', 'reference_files', 'held_back', 'held_back_reason', 'held_back_note'}
PRODUCT = {'id', 'name', 'kind', 'category', 'summary', 'developer', 'version', 'licence', 'licensing',
           'formats', 'homepage', 'account', 'description', 'download', 'cabinet', 'note', 'references'}
DOWNLOAD = {'source', 'url', 'sha256', 'demo_url', 'demo_sha256'}
SETUP = {'prefix', 'runner', 'dxvk', 'sync', 'winetricks', 'env', 'virtual_desktop', 'launch', 'launch_args',
         'launch_helper', 'launch_service', 'url_scheme', 'keep', 'data', 'relink', 'script', 'recover_script'}
KINDS = {'windows', 'native'}


class LeadError(ValueError):
    pass


def _check(path, table, allowed, where):
    unknown = set(table) - allowed
    if unknown:
        raise LeadError(f'{path.name}: unknown {where} fields: ' + ', '.join(sorted(unknown)))


def load_file(path):
    path = Path(path)
    with path.open('rb') as handle:
        data = tomllib.load(handle)
    _check(path, data, TOP, 'top-level')
    if data.get('schema') != 1:
        raise LeadError(path.name + ': unsupported lead schema')
    required = ('source', 'licence', 'vendor') if data.get('source') == 'plugg' else \
        ('source', 'source_url', 'source_commit', 'licence', 'vendor')
    for key in required:
        if not isinstance(data.get(key), str) or not data[key]:
            raise LeadError(f'{path.name}: {key} is required')
    products = data.get('products')
    if not isinstance(products, list) or not products:
        raise LeadError(path.name + ': no products')
    for product in products:
        _check(path, product, PRODUCT, 'product')
        if product.get('kind') not in KINDS:
            raise LeadError(f'{path.name}: {product.get("id")}: kind must be windows or native')
        if not product.get('id') or not product.get('name'):
            raise LeadError(path.name + ': every product needs an id and a name')
        download = product.get('download', {})
        _check(path, download, DOWNLOAD, 'download')
        for key in ('sha256', 'demo_sha256'):
            if key in download and not SHA256.fullmatch(download[key]):
                raise LeadError(f'{path.name}: {product["id"]}: {key} is not a SHA-256')
        for key in ('url', 'demo_url'):
            if key in download and not download[key].startswith('https://'):
                raise LeadError(f'{path.name}: {product["id"]}: {key} must be HTTPS')
        _check(path, product.get('cabinet', {}), SETUP, 'cabinet')
    for script in product_scripts(data):
        if script not in data.get('reference_scripts', {}):
            raise LeadError(f'{path.name}: script {script} is named but not included')
    data['file'] = path.name
    return data


def product_scripts(data):
    return sorted({product['cabinet'][key] for product in data['products']
                   for key in ('script', 'recover_script') if key in product.get('cabinet', {})})


def load_all(directory=DIRECTORY):
    return [load_file(path) for path in sorted(Path(directory).glob('*/*.toml'))]


def _fold(text):
    return re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()


def products(files=None):
    """Every product, flattened, with its file's vendor and source beside it."""
    for data in files if files is not None else load_all():
        for product in data['products']:
            yield {**product, 'vendor': data['vendor'], 'source': data['source'],
                   'source_url': data.get('source_url', ''), 'source_commit': data.get('source_commit', ''),
                   'source_path': data.get('source_path', ''), 'file': data['file'],
                   'held_back': data.get('held_back', False), 'held_back_reason': data.get('held_back_reason'),
                   'support_files': sorted(data.get('reference_files', {}))}


def search(query='', files=None):
    """Products whose name, vendor, developer or id contain every word of the query."""
    words = _fold(query or '').split()
    found = []
    for product in products(files):
        haystack = ' '.join(_fold(product.get(key, '')) for key in ('name', 'vendor', 'developer', 'id', 'category'))
        if all(word in haystack for word in words):
            found.append(product)
    return found


def for_vendor(vendor, files=None):
    """Leads for a vendor name, matched on whole words so 'TAL' does not match 'Digital'."""
    wanted = _fold(vendor or '')
    if not wanted:
        return []
    found = []
    for product in products(files):
        names = {_fold(product['vendor']), _fold(product.get('developer', ''))}
        if any(name and (wanted == name or f' {wanted} ' in f' {name} ' or f' {name} ' in f' {wanted} ')
               for name in names):
            found.append(product)
    return found


def for_file(sha256, files=None):
    """Leads whose recorded download is exactly this file."""
    return [product for product in products(files)
            if sha256 in (product.get('download', {}).get('sha256'), product.get('download', {}).get('demo_sha256'))]


def native(found):
    return [product for product in found if product['kind'] == 'native']


def attribution(product):
    if product['source'] == 'plugg':
        return "Plugg's own note (" + ', '.join(product.get('references', [])) + ')' if product.get('references') \
            else "Plugg's own note."
    return (f"From {product['source'].capitalize()} ({product['source_url']}), "
            f"{product['source_path']} at {product['source_commit'][:12]}.")


def recipes_for(product, records):
    """This project's own vendor recipes for the same vendor, newest revision of each."""
    names = {_fold(product['vendor']), _fold(product.get('developer', ''))} - {''}
    newest = {}
    for reference, record in records.items():
        data = record['data']
        if data.get('kind') == 'vendor' and _fold(data.get('vendor', '')) in names:
            if data['id'] not in newest or data['revision'] > newest[data['id']][1]:
                newest[data['id']] = (reference, data['revision'])
    return sorted(reference for reference, _ in newest.values())


def render(product, ours=()):
    lines = [f"{product['name']} — {product['vendor']} ({product['kind']})"]
    if ours:
        lines.append('  This project already has a recipe for this vendor: ' + ', '.join(ours)
                     + '. Compare before writing another.')
    if product.get('summary'):
        lines.append('  ' + product['summary'])
    if product['kind'] == 'native':
        lines.append('  Has a native Linux build: use it rather than bridging the Windows version. '
                     'Plugg does not install or manage native plug-ins.')
    if product.get('note'):
        lines.append('  ' + product['note'])
    if product['held_back']:
        lines.append('  Held back by its source: ' + product['held_back_reason'])
    download = product.get('download', {})
    if download.get('url'):
        lines.append('  Download: ' + download['url'])
    if download.get('sha256'):
        lines.append('  SHA-256 of that download: ' + download['sha256'])
    if download.get('source') == 'byo':
        lines.append('  The user supplies the installer.')
    setup = product.get('cabinet', {})
    hints = [f'{key}={_hint(value)}' for key, value in setup.items() if key not in ('script', 'recover_script', 'prefix')]
    if hints:
        lines.append('  Setup the source used (plain Wine, not tested here): ' + ', '.join(hints))
    if setup.get('script'):
        lines.append(f"  Install steps: reference_scripts.\"{setup['script']}\" in leads/{product['source']}/{product['file']}")
        if product.get('support_files'):
            lines.append('  The script also reads: ' + ', '.join(product['support_files'])
                         + ' (reference_files in the same file)')
    lines.append('  ' + attribution(product))
    return '\n'.join(lines)


def _hint(value):
    if isinstance(value, list):
        return ' '.join(value)
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    return value


def scaffold_comment(found):
    """Comment lines for a generated recipe, pointing at what a lead already knows."""
    if not found:
        return []
    lines = ['# Leads for this vendor (research, untested here). See "recipe leads".']
    for product in found:
        lines.append('#   ' + product['name'] + (', native Linux build exists' if product['kind'] == 'native' else ''))
        setup = product.get('cabinet', {})
        if setup.get('launch'):
            lines.append('#     installs to ' + setup['launch'])
        if setup.get('winetricks'):
            lines.append('#     winetricks in the source: ' + ', '.join(setup['winetricks']))
    lines.append('#   ' + attribution(found[0]))
    return lines
