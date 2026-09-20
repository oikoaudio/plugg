"""Protect activated environments from silent changes to their licensing identity.

Two failure modes matter and they are not the same.

* **Machine-bound activations** (iLok/PACE and comparable schemes) treat one
  Windows environment as one computer. Recreating its prefix, moving it, or
  rewriting the identity values inside it makes the vendor see a different
  machine. The seat is recoverable, but only if the user deactivates first.
* **Limited activations** spend a finite number of validations per serial
  number. Nothing can be deactivated to get one back. Losing one means the
  user has to buy the product again.

Many products are neither: their serial can be entered again as often as
needed. Which is which is a property of the product, not something this
project can detect, so it is recorded per product by the person who activated
it and defaults to the strictest interpretation when unknown.

Nothing here inspects, alters, emulates or bypasses a licensing check. This
module only stops *our own* operations from destroying the user's activations,
and records enough evidence for a person to tell whether an environment still
looks like the machine their licences were issued to.

Nothing secret is written down. Identity values are recorded as keyed hashes
under a random per-environment key kept in a separate 0600 file, never in the
clear, so ``licensing.json`` can be attached to a bug report without becoming a
copy of the machine identifiers. Several of those values are short and
structured, so an unkeyed hash of them would be trivially recoverable; keep the
key file out of anything you share, and the record alone reveals nothing.
Serial numbers, credentials, licence files and account data belong in the
vendor's own manager, exactly as they would on any other computer; they are
never collected here and must never be pasted into a product name or note.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time

from . import core

RECORD = 'licensing.json'
#: Per-environment hashing key. Kept beside the record but never inside it, and
#: never in a recovery-point manifest, so the record stays shareable.
KEY = '.licensing-key'
BACKUPS = 'licensing-backups'
SCHEMA = 1
ACKNOWLEDGEMENT_SECONDS = 2 * 60 * 60

#: Recovery classes, weakest constraint first. ``unknown`` is deliberately as
#: strict as ``limited-activations``: an unrecorded product is not a safe one.
#: ``unlicensed`` is first because it is the weakest claim of all: there is
#: nothing to lose. It is not the same as ``reactivatable``, which means a
#: serial you can type again — a free plug-in has no serial to type.
RECOVERY = ('unlicensed', 'reactivatable', 'deactivate-first', 'limited-activations', 'unknown')

CONFIRMATION = {
    'unlicensed': 'CHANGE THIS ENVIRONMENT',
    'reactivatable': 'CHANGE THIS ENVIRONMENT',
    'deactivate-first': 'I HAVE DEACTIVATED THIS ENVIRONMENT',
    'limited-activations': 'I ACCEPT LOSING A LIMITED ACTIVATION',
    'unknown': 'I ACCEPT LOSING A LIMITED ACTIVATION',
}

EXPLANATION = {
    'unlicensed': 'Nothing here needed activating. Rebuilding costs the time to install it again.',
    'reactivatable': 'Its serial numbers can be activated again.',
    'deactivate-first': 'Its licences are bound to this environment as one machine. '
                        'Deactivate them in the vendor or iLok manager before changing it.',
    'limited-activations': 'At least one product here has a finite number of activations '
                           'that cannot be recovered by deactivating anything.',
    'unknown': 'At least one product here has no recorded recovery method, so it is '
               'treated as if its activations cannot be recovered.',
}

#: Operations that only read, launch or publish. Always allowed.
READ_ONLY = frozenset({'status', 'verify', 'scan', 'publish', 'launch', 'open_helper',
                       'open_licensing_manager', 'stop_session', 'archive'})
#: Operations that write inside an existing prefix without touching the values
#: below. Allowed, but refused while the recorded identity already disagrees
#: with the environment, because that means something changed unnoticed.
IN_PLACE = frozenset({'configure_graphics', 'install_component', 'install_dependency',
                      'install_helper', 'install_vc_runtime', 'import_module',
                      'prepare_archive_tools'})
#: Operations that create, replace, relocate or discard machine identity.
IDENTITY_CHANGING = frozenset({'create_prefix', 'recreate_prefix', 'reset_prefix',
                               'remove_environment', 'move_environment', 'replace_runtime',
                               'restore_identity', 'rewrite_identity'})

#: Registry values vendors read to decide which computer this is. Sections are
#: written without their hive prefix, exactly as Wine stores them in system.reg.
IDENTITY = (
    ('machine_guid', r'Software\Microsoft\Cryptography', 'MachineGuid'),
    ('windows_product_id', r'Software\Microsoft\Windows NT\CurrentVersion', 'ProductId'),
    ('windows_digital_product_id', r'Software\Microsoft\Windows NT\CurrentVersion', 'DigitalProductId'),
    ('windows_install_date', r'Software\Microsoft\Windows NT\CurrentVersion', 'InstallDate'),
    ('computer_name', r'System\ControlSet001\Control\ComputerName\ComputerName', 'ComputerName'),
    ('active_computer_name', r'System\ControlSet001\Control\ComputerName\ActiveComputerName', 'ComputerName'),
    ('tcpip_hostname', r'System\ControlSet001\Services\Tcpip\Parameters', 'Hostname'),
    ('mounted_device_c', r'System\MountedDevices', r'\DosDevices\C:'),
)

#: Files copied by :func:`backup`. Small, and enough to restore the identity
#: values above without touching installed products or activation payloads.
IDENTITY_FILES = ('system.reg', 'user.reg', 'userdef.reg', 'version', 'config_info',
                  '.plugg-runtime', '.update-timestamp')

MAX_REGISTRY_BYTES = 128 * 1024 * 1024
VALUE = re.compile(r'"((?:[^"\\]|\\.)*)"=(.*)$')


class LicensedEnvironmentError(core.HostError):
    """Refusal to change an environment that holds activations."""


def _unescape(text):
    return re.sub(r'\\(.)', r'\1', text)


def _registry_values(path, wanted):
    """Read selected Wine registry values without loading the whole file."""
    if path.stat().st_size > MAX_REGISTRY_BYTES:
        raise core.HostError('The environment registry is too large to inspect: ' + str(path))
    sections = {section.casefold(): {name.casefold() for _, _, name in entries}
                for section, entries in wanted.items()}
    found, section, pending = {}, None, None
    with path.open('r', encoding='utf-8', errors='replace') as stream:
        for line in stream:
            line = line.rstrip('\n').rstrip('\r')
            if pending is not None:
                pending[2].append(line.strip().rstrip('\\'))
                if not line.rstrip().endswith('\\'):
                    found[pending[0], pending[1]] = ''.join(pending[2])
                    pending = None
                continue
            if line.startswith('['):
                end = line.find(']')
                section = line[1:end].replace('\\\\', '\\').casefold() if end > 1 else None
                continue
            if section is None or section not in sections or not line.startswith('"'):
                continue
            match = VALUE.match(line)
            if match is None:
                continue
            name = _unescape(match.group(1)).casefold()
            if name not in sections[section]:
                continue
            value = match.group(2)
            if value.rstrip().endswith('\\'):
                pending = (section, name, [value.strip().rstrip('\\')])
                continue
            found[section, name] = value
    return found


def _normalize(value):
    if value is None:
        return None
    value = value.strip()
    if value.startswith('"') and value.endswith('"') and len(value) > 1:
        return _unescape(value[1:-1])
    return value


def identity(environment):
    """Observe the identity values and location of an environment's prefix.

    Values are reduced to salted hashes immediately and never returned in the
    clear: this is enough to tell that ``machine_guid`` changed without the
    record becoming a copy of it. A value that is absent or unreadable is
    recorded as absent, never invented, and an environment whose registry
    cannot be read has an unknown identity, which counts as a mismatch.
    """
    environment = Path(environment)
    prefix = environment / 'prefix'
    key = _key(environment)
    wanted = {}
    for label, section, name in IDENTITY:
        wanted.setdefault(section, []).append((label, section, name))
    values = {label: {'present': False, 'digest': None} for label, _, _ in IDENTITY}
    registry = prefix / 'system.reg'
    issues = []
    if key is None:
        # A protected environment without its key can compare nothing, which is
        # a mismatch rather than a match: it has to be re-examined. An
        # environment that was never protected simply has no key yet.
        key = secrets.token_bytes(32)
        if (environment / RECORD).exists():
            issues.append(KEY + ': missing or damaged')
    if registry.is_file():
        try:
            found = _registry_values(registry, wanted)
            for label, section, name in IDENTITY:
                values[label] = _digest_value(key, label, _normalize(found.get((section.casefold(), name.casefold()))))
        except (OSError, core.HostError) as exc:
            issues.append('system.reg: ' + str(exc))
    else:
        issues.append('system.reg: not found')
    drive = prefix / 'dosdevices/c:'
    location = {
        'prefix': str(prefix.resolve()) if prefix.exists() else str(prefix),
        'drive_c': os.readlink(drive) if drive.is_symlink() else None,
        'runtime_version': _read_line(prefix / 'version'),
        'runtime_marker': _read_line(prefix / '.plugg-runtime'),
    }
    return {'schema': SCHEMA, 'values': values, 'location': location, 'issues': issues,
            'fingerprint': fingerprint(values)}


def _read_line(path):
    try:
        with path.open('r', encoding='utf-8', errors='replace') as stream:
            return stream.readline(4096).strip() or None
    except (OSError, ValueError):
        return None


def _key(environment, create=False):
    """Read, or first create, this environment's hashing key."""
    path = Path(environment) / KEY
    try:
        material = bytes.fromhex(path.read_text().strip())
        if len(material) == 32:
            return material
        raise ValueError('malformed')
    except (OSError, ValueError):
        if not create:
            return None
    material = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(material.hex() + '\n')
    # The mode argument applies only when the file is created, and this key is
    # the only thing keeping the record from being a copy of the identifiers.
    os.chmod(path, 0o600)
    return material


def _digest_value(key, label, value):
    """Reduce one identity value to a keyed hash, or record it as absent."""
    if value is None:
        return {'present': False, 'digest': None}
    material = ('plugg/licensing/1\0' + label + '\0' + value).encode('utf-8')
    return {'present': True, 'digest': hmac.new(key, material, 'sha256').hexdigest()}


def fingerprint(values):
    """Hash the observed identity digests, including which values were absent."""
    canonical = json.dumps({key: values.get(key) for key, _, _ in IDENTITY}, sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def validate_products(products):
    if not isinstance(products, list) or not products:
        raise ValueError('Record at least one product, with its recovery method')
    seen, checked = set(), []
    for item in products:
        if not isinstance(item, dict) or set(item) - {'name', 'recovery', 'activations_remaining',
                                                      'note', 'deactivate_at'}:
            raise ValueError('Product requires name and recovery, with optional '
                             'activations_remaining, deactivate_at and note')
        name = item.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Product name must be nonempty text')
        if len(name.strip()) > 120:
            raise ValueError('Product name must be short. Record the product, not its licence details.')
        if name.strip().casefold() in seen:
            raise ValueError('Duplicate product: ' + name)
        seen.add(name.strip().casefold())
        recovery = item.get('recovery', 'unknown')
        if recovery not in RECOVERY:
            raise ValueError('Product recovery must be one of: ' + ', '.join(RECOVERY))
        remaining = item.get('activations_remaining')
        if remaining is not None and (type(remaining) is not int or remaining < 0):
            raise ValueError('activations_remaining must be a non-negative whole number')
        where = item.get('deactivate_at')
        if where is not None and (not isinstance(where, str) or not where.strip()):
            raise ValueError('deactivate_at must be nonempty text')
        if where is not None and len(where.strip()) > 200:
            raise ValueError('deactivate_at must be short: where to go, not how to sign in')
        note = item.get('note')
        if note is not None and (not isinstance(note, str) or not note.strip()):
            raise ValueError('Product note must be nonempty text')
        if note is not None and len(note.strip()) > 512:
            raise ValueError('Product note must be short. Never record serial numbers or credentials here.')
        entry = {'name': name.strip(), 'recovery': recovery}
        if remaining is not None:
            entry['activations_remaining'] = remaining
        if note is not None:
            entry['note'] = note.strip()
        checked.append(entry)
    return sorted(checked, key=lambda item: item['name'].casefold())


def severity(products):
    """The strictest recovery class among the recorded products."""
    return max((item.get('recovery', 'unknown') for item in products),
               key=lambda value: RECOVERY.index(value) if value in RECOVERY else len(RECOVERY),
               default='unknown')


def required_confirmation(products):
    return CONFIRMATION[severity(products)]


def read(environment):
    """Return the licensing record, or ``None`` when the environment is not protected."""
    path = Path(environment) / RECORD
    try:
        with path.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
    except FileNotFoundError:
        return None
    if len(raw) > 1024 * 1024:
        raise core.HostError('The licensing record is too large to read: ' + str(path))
    try:
        record = json.loads(raw)
    except ValueError as exc:
        raise core.HostError('The licensing record could not be read: ' + str(exc)) from exc
    if not isinstance(record, dict) or record.get('schema') != SCHEMA:
        raise core.HostError('Unsupported licensing record: ' + str(path))
    return record


def validate_declaration(data):
    """Check what a recipe says about its vendor's licensing.

    A recipe may state the vendor and what happens if an environment holding
    its products is rebuilt. It may not state how many activations remain:
    that is a fact about one person's purchase, not about the product, and a
    recipe shared with strangers has no business carrying it.
    """
    if not isinstance(data, dict):
        raise ValueError('licensing must be a table')
    unknown = set(data) - {'vendor', 'recovery', 'note', 'deactivate_at'}
    if unknown:
        raise ValueError('Unknown licensing fields: ' + ', '.join(sorted(unknown)))
    for key in ('vendor', 'recovery'):
        if key not in data:
            raise ValueError('licensing requires ' + key)
    if data['recovery'] not in RECOVERY:
        raise ValueError('licensing recovery must be one of: ' + ', '.join(RECOVERY))
    for key, limit in (('vendor', 120), ('note', 512), ('deactivate_at', 200)):
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError('licensing ' + key + ' must be nonempty text')
        if len(value) > limit:
            raise ValueError('licensing ' + key + ' must be at most %d characters' % limit)
    return data


def protect_declared(environment, declaration):
    """Record what the recipe already knew, as soon as the environment exists.

    Whether losing an activation can be undone is a fact about the vendor, not
    a judgement the person installing should be asked to make. They are
    thinking about a plug-in; the answer is the same for everyone who ever
    installs that product, and the moment they would think to ask is the
    moment it is already too late. So a recipe states it once, and every
    environment built from that recipe is protected before it has anything to
    lose.

    It also carries where deactivation happens, when the recipe says so.
    "Deactivate before rebuilding" is not advice anyone can act on if they do
    not know that this vendor means a website, that one means the iLok manager
    and the next means uninstalling through its own helper.

    Only the vendor's name, what happens on a rebuild and where to go are
    recorded. No serial number, credential or account detail is collected here
    or anywhere.
    """
    if not declaration:
        return None
    declaration = validate_declaration(declaration)
    product = {'name': declaration['vendor'], 'recovery': declaration['recovery']}
    if declaration.get('deactivate_at'):
        product['deactivate_at'] = declaration['deactivate_at']
    return protect(environment, [product], note=declaration.get('note'))


def protect(environment, products, *, note=None):
    """Record what an environment is licensed for and what it looks like now.

    Run this once the activations are in place. Adding products later merges
    them by name and re-reads the identity baseline from the environment.
    """
    environment = Path(environment)
    if not (environment / 'prefix').is_dir():
        raise core.HostError('This is not a managed environment directory: ' + str(environment))
    products = validate_products(products)
    if note is not None and (not isinstance(note, str) or not note.strip()):
        raise ValueError('Note must be nonempty text')
    if note is not None and len(note.strip()) > 512:
        raise ValueError('Note must be short. Never record serial numbers or credentials here.')
    with core.lock(environment / '.licensing.lock'):
        existing = read(environment) or {}
        _key(environment, create=True)
        merged = {item['name'].casefold(): item for item in existing.get('products', [])}
        merged.update({item['name'].casefold(): item for item in products})
        observed = identity(environment)
        record = {
            'schema': SCHEMA,
            'protected': True,
            'products': sorted(merged.values(), key=lambda item: item['name'].casefold()),
            'protected_since': existing.get('protected_since') or _now(),
            'recorded_at': _now(),
            'identity': observed,
            'acknowledgement': existing.get('acknowledgement'),
            'note': note if note is not None else existing.get('note'),
            'limits': 'Records the identity values this project can observe. Vendors may '
                      'also read host details outside the prefix, such as network hardware.',
        }
        core.atomic_json(environment / RECORD, record)
    return record


def deactivation_phrase(names):
    return 'I have deactivated ' + ', '.join(sorted(names, key=str.casefold))


def deactivated(environment, names, confirmation):
    """Record that the user deactivated products; this project never checks that itself.

    The products move from what the environment holds to its history. When none
    are left, the environment stops being protected, because nothing in it can
    be lost any more. The identity record and recovery points are kept.
    """
    environment = Path(environment)
    record = read(environment)
    if record is None:
        raise core.HostError('This environment has no licensing record.')
    wanted = {name.strip().casefold(): name.strip() for name in names if name.strip()}
    if not wanted:
        raise ValueError('Name at least one product you deactivated')
    held = {item['name'].casefold(): item for item in record.get('products', [])}
    unknown = sorted(name for key, name in wanted.items() if key not in held)
    if unknown:
        raise ValueError('Not recorded in this environment: ' + ', '.join(unknown)
                         + '. Recorded: ' + ', '.join(item['name'] for item in record.get('products', [])))
    phrase = deactivation_phrase([held[key]['name'] for key in wanted])
    if confirmation != phrase:
        raise LicensedEnvironmentError('Deactivate the products with their vendor first. Then, to record it, '
                                       'repeat exactly: ' + phrase)
    with core.lock(environment / '.licensing.lock'):
        record = read(environment)
        stamp = _now()
        remaining = [item for item in record.get('products', []) if item['name'].casefold() not in wanted]
        released = [*record.get('deactivated', []),
                    *({**item, 'deactivated_at': stamp} for item in record.get('products', [])
                      if item['name'].casefold() in wanted)]
        updated = {**record, 'products': remaining, 'deactivated': released}
        if not remaining:
            updated.update(protected=False, unprotected_at=stamp, acknowledgement=None,
                           unprotected_because='Every recorded product was deactivated by the user.')
        core.atomic_json(environment / RECORD, updated)
    return updated


def unprotect(environment, confirmation):
    """Remove protection. Requires the same confirmation as changing the environment."""
    record = read(environment)
    if record is None:
        raise core.HostError('This environment is not protected.')
    expected = required_confirmation(record.get('products', []))
    if confirmation != expected:
        raise LicensedEnvironmentError('To stop protecting this environment, repeat exactly: ' + expected)
    with core.lock(Path(environment) / '.licensing.lock'):
        updated = {**read(environment), 'protected': False, 'unprotected_at': _now(), 'acknowledgement': None}
        core.atomic_json(Path(environment) / RECORD, updated)
    return updated


def verify(environment):
    """Compare the environment with its recorded licensing identity."""
    record = read(environment)
    observed = identity(environment)
    if record is None or not record.get('protected'):
        return {'protected': False, 'matches': None, 'drift': [], 'observed': observed,
                'products': (record or {}).get('products', []), 'severity': None}
    recorded = record.get('identity', {})
    drift = []
    for key, _, _ in IDENTITY:
        was = recorded.get('values', {}).get(key) or {'present': False, 'digest': None}
        now = observed['values'][key]
        if was == now:
            continue
        change = ('appeared' if not was.get('present') else
                  'disappeared' if not now.get('present') else 'changed')
        drift.append({'value': key, 'change': change})
    location = recorded.get('location', {})
    moved = [{'value': key, 'recorded': location.get(key), 'observed': observed['location'][key]}
             for key in ('prefix', 'drive_c', 'runtime_version', 'runtime_marker')
             if location.get(key) != observed['location'][key]]
    return {'protected': True, 'matches': not drift and not observed['issues'],
            'drift': drift, 'location_drift': moved, 'observed': observed,
            'machine_identity_is_this_computer': is_this_computer(environment),
            'products': record.get('products', []), 'severity': severity(record.get('products', [])),
            'acknowledgement': _valid_acknowledgement(record)}


def _valid_acknowledgement(record):
    ack = record.get('acknowledgement')
    if not isinstance(ack, dict) or ack.get('consumed'):
        return None
    if not isinstance(ack.get('expires'), (int, float)) or ack['expires'] < time.time():
        return None
    return ack


def acknowledge(environment, operation, confirmation, *, note=None):
    """Record that the user accepted the licensing consequences of one operation.

    The acknowledgement covers a single operation, expires, and is consumed
    when that operation runs. It is never created on the user's behalf.
    """
    record = read(environment)
    if record is None or not record.get('protected'):
        raise core.HostError('This environment is not protected; no acknowledgement is needed.')
    if operation not in IDENTITY_CHANGING and operation not in IN_PLACE:
        raise ValueError('Unknown operation: ' + operation)
    expected = required_confirmation(record.get('products', []))
    if confirmation != expected:
        raise LicensedEnvironmentError(
            _refusal(record, operation) + '\n\nIf that is done, repeat exactly: ' + expected)
    with core.lock(Path(environment) / '.licensing.lock'):
        current = read(environment)
        ack = {'schema': SCHEMA, 'operation': operation, 'recorded_at': _now(),
               'expires': time.time() + ACKNOWLEDGEMENT_SECONDS,
               'severity': severity(current.get('products', [])), 'consumed': False,
               'note': note.strip() if isinstance(note, str) and note.strip() else None}
        core.atomic_json(Path(environment) / RECORD, {**current, 'acknowledgement': ack})
    return ack


def consume(environment, operation):
    """Mark the acknowledgement for one operation as used."""
    with core.lock(Path(environment) / '.licensing.lock'):
        record = read(environment)
        if record is None:
            return None
        ack = _valid_acknowledgement(record)
        if ack is None or ack['operation'] != operation:
            return None
        used = {**ack, 'consumed': True, 'consumed_at': _now()}
        core.atomic_json(Path(environment) / RECORD, {**record, 'acknowledgement': used})
        return used


def _refusal(record, operation):
    products = record.get('products', [])
    level = severity(products)
    limited = [item['name'] + (f" ({item['activations_remaining']} activations left)"
                               if item.get('activations_remaining') is not None else '')
               for item in products if item.get('recovery') in ('limited-activations', 'unknown')]
    bound = [item['name'] for item in products if item.get('recovery') == 'deactivate-first']
    lines = ['This environment holds activations, so ' + operation.replace('_', ' ') +
             ' has been refused.', EXPLANATION[level]]
    if bound:
        lines.append('Deactivate first: ' + ', '.join(bound) + '.')
    if limited:
        lines.append('Cannot be recovered by deactivating: ' + ', '.join(limited) + '.')
    return '\n'.join(lines)


def _refuse_wrong_directory(place):
    """Fail when handed something that is not the environment directory.

    A path with no record reads as unprotected, so an off-by-one in a caller —
    the prefix instead of its parent, or the directory holding every
    environment — would silently disable the protection rather than raise. A
    directory that simply has no record yet is fine; one that is obviously the
    wrong level is not.
    """
    if (place / RECORD).is_file():
        return
    if place.name in ('prefix', 'drive_c') or (place.parent / RECORD).is_file():
        raise core.HostError('Licensing is recorded for the environment directory, not for '
                             'part of it: ' + str(place))
    try:
        children = [child for child in place.iterdir() if child.is_dir()]
    except OSError:
        return
    protected = [child.name for child in children[:512] if (child / RECORD).is_file()]
    if protected:
        raise core.HostError('This directory holds managed environments rather than being one '
                             '(' + ', '.join(sorted(protected)[:3]) + '): ' + str(place))


def guard(environment, operation):
    """Refuse an operation that would risk the recorded activations.

    Read-only operations always pass. In-place operations pass unless the
    environment no longer matches its recorded identity, which means something
    already changed and should be understood before more is written. Operations
    that create, replace, relocate or discard identity require an explicit,
    unexpired acknowledgement recorded by the user.
    """
    if operation not in READ_ONLY | IN_PLACE | IDENTITY_CHANGING:
        raise ValueError('Unknown operation: ' + operation)
    _refuse_wrong_directory(Path(environment))
    record = read(environment)
    if record is None or not record.get('protected'):
        return {'protected': False, 'operation': operation, 'allowed': True}
    if operation in READ_ONLY:
        return {'protected': True, 'operation': operation, 'allowed': True, 'acknowledged': False}
    state = verify(environment)
    ack = state.get('acknowledgement')
    acknowledged = bool(ack and ack['operation'] == operation)
    if operation in IN_PLACE:
        if state['matches'] or acknowledged:
            return {'protected': True, 'operation': operation, 'allowed': True,
                    'acknowledged': acknowledged, 'verification': state}
        raise LicensedEnvironmentError(
            'This environment no longer matches the identity recorded when its licences were '
            'activated, so ' + operation.replace('_', ' ') + ' has been refused.\n' +
            _drift_summary(state) + '\nCheck whether your products still authorize here before '
            'changing anything else. ' + EXPLANATION[state['severity']])
    if acknowledged:
        # Single use is the point: an acknowledgement authorizes the operation
        # the user thought about, once, not every repeat within two hours.
        consume(environment, operation)
        return {'protected': True, 'operation': operation, 'allowed': True,
                'acknowledged': True, 'verification': state}
    raise LicensedEnvironmentError(_refusal(record, operation))


def _drift_summary(state):
    changed = [item['value'] for item in state.get('drift', [])]
    moved = [item['value'] for item in state.get('location_drift', [])]
    issues = state['observed'].get('issues', [])
    parts = []
    if changed:
        parts.append('Changed identity values: ' + ', '.join(changed) + '.')
    if moved:
        parts.append('Changed location or runtime: ' + ', '.join(moved) + '.')
    if issues:
        parts.append('Could not read: ' + '; '.join(issues) + '.')
    return '\n'.join(parts) or 'No specific difference was recorded.'


def backup(environment, *, label=None):
    """Copy the identity files to a recovery point inside the environment.

    This is small: registry files and runtime markers, not installed products
    and not activation payloads. It is a way back from an identity change, not
    a full environment backup and not a snapshot.
    """
    environment = Path(environment)
    prefix = environment / 'prefix'
    if not prefix.is_dir():
        raise core.HostError('This is not a managed environment directory: ' + str(environment))
    if label is not None and not re.fullmatch(r'[A-Za-z0-9._-]{1,48}', label):
        raise ValueError('Backup label may use letters, digits, dot, dash and underscore only')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + (('-' + label) if label else '')
    target = environment / BACKUPS / stamp
    if target.exists():
        raise core.HostError('A recovery point with this name already exists: ' + str(target))
    target.mkdir(parents=True)
    files = []
    for name in IDENTITY_FILES:
        source = prefix / name
        if not source.is_file():
            continue
        shutil.copy2(source, target / name)
        files.append({'name': name, 'sha256': core.digest(target / name),
                      'bytes': (target / name).stat().st_size})
    record = read(environment) or {}
    observed = identity(environment)
    manifest = {'schema': SCHEMA, 'created': _now(), 'environment': str(environment.resolve()),
                'files': files,
                # Fingerprint only: the per-value digests and the products stay
                # in the record, so a manifest can be shared on its own.
                'identity': {'schema': SCHEMA, 'fingerprint': observed['fingerprint'],
                             'location': observed['location'], 'issues': observed['issues']},
                'products': [item['name'] for item in record.get('products', [])],
                'limits': 'Identity files only. Installed products, activation payloads and '
                          'user data are not copied and cannot be restored from here. The copied '
                          'registry files contain this machine\'s identifiers in the clear: keep '
                          'the recovery point private, unlike the licensing record itself.'}
    core.atomic_json(target / 'manifest.json', manifest)
    return manifest


def backups(environment):
    directory = Path(environment) / BACKUPS
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.iterdir()):
        manifest = path / 'manifest.json'
        if manifest.is_file():
            try:
                found.append({'id': path.name, 'path': str(path), **json.loads(manifest.read_text())})
            except (OSError, ValueError):
                found.append({'id': path.name, 'path': str(path), 'unreadable': True})
    return found


def restore(environment, backup_id, confirmation):
    """Restore identity files from a recovery point.

    Refuses while plug-ins from this environment are running, takes a fresh
    recovery point of the current state first, and verifies every file it
    writes against the manifest.
    """
    environment = Path(environment)
    record = read(environment)
    expected = required_confirmation((record or {}).get('products', []))
    if confirmation != expected:
        raise LicensedEnvironmentError('Restoring identity files changes what vendors see. '
                                       'To continue, repeat exactly: ' + expected)
    source = environment / BACKUPS / backup_id
    manifest_path = source / 'manifest.json'
    if not manifest_path.is_file():
        raise core.HostError('No such recovery point: ' + str(source))
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != SCHEMA:
        raise core.HostError('Unsupported recovery point: ' + str(source))
    from . import vendors
    prefix = environment / 'prefix'
    running = vendors.applications(prefix)
    if running:
        raise core.HostError('Close this environment’s plug-ins and helpers first: ' + ', '.join(sorted(running)))
    for item in manifest['files']:
        if core.digest(source / item['name']) != item['sha256']:
            raise core.HostError('Recovery point file changed since it was created: ' + item['name'])
    with core.lock(environment / '.licensing.lock'):
        previous = backup(environment, label='before-restore')
        for item in manifest['files']:
            shutil.copy2(source / item['name'], prefix / item['name'])
    return {'restored': backup_id, 'files': [item['name'] for item in manifest['files']],
            'previous_state': previous['created'], 'identity': identity(environment)}


def status(environment):
    """Summarize protection, products and observed drift for display."""
    state = verify(environment)
    record = read(environment)
    return {'environment': str(Path(environment).resolve()), 'protected': state['protected'],
            'products': state['products'], 'severity': state['severity'],
            'matches_recorded_identity': state['matches'],
            'machine_identity_is_this_computer': is_this_computer(environment),
            'drift': state.get('drift', []), 'location_drift': state.get('location_drift', []),
            'acknowledgement': state.get('acknowledgement'),
            'recovery_points': [item['id'] for item in backups(environment)],
            'protected_since': (record or {}).get('protected_since'),
            'note': (record or {}).get('note'),
            'limits': 'Observed identity values only. A matching record is not proof that a '
                      'product is still authorized, and vendors may read host details this '
                      'project cannot see.'}


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


#: Where the host's stable identifier lives on a systemd machine.
MACHINE_ID_SOURCES = ('/etc/machine-id', '/var/lib/dbus/machine-id')
#: Fallback identity for a computer without one, kept per library.
LIBRARY_IDENTITY = 'machine-identity'
GUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _as_guid(digest):
    return '-'.join((digest[:8], digest[8:12], digest[12:16], digest[16:20], digest[20:32]))


def host_machine_guid(library=None):
    """One Windows machine identity for this computer.

    Wine generates a fresh MachineGuid for every prefix it creates, so a
    computer running several managed environments presents as several different
    machines to any vendor that fingerprints on that value. Licences are sold
    per machine, so that quietly spends a person's machine allowance on
    environments that are all one desk.

    The value is derived from the host's own machine-id by hashing, so it is the
    same for every environment on this computer, stable across libraries and
    reinstalls, and does not hand the host identifier itself to Windows
    software. A computer without a machine-id gets one generated per library.
    """
    for source in MACHINE_ID_SOURCES:
        try:
            material = Path(source).read_text().strip()
        except OSError:
            continue
        if material:
            return _as_guid(hashlib.sha256(('plugg/machine/1\0' + material).encode()).hexdigest())
    if library is None:
        return None
    path = Path(library) / LIBRARY_IDENTITY
    try:
        existing = path.read_text().strip()
        if GUID.fullmatch(existing):
            return existing
    except OSError:
        pass
    value = _as_guid(hashlib.sha256(secrets.token_bytes(32)).hexdigest())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + '\n')
    except OSError:
        return None
    return value


def current_machine_guid(environment):
    """The MachineGuid a prefix currently reports, or None if it has none yet."""
    registry = Path(environment) / 'prefix/system.reg'
    if not registry.is_file():
        return None
    label, section, name = IDENTITY[0]
    try:
        found = _registry_values(registry, {section: [(label, section, name)]})
    except (OSError, core.HostError):
        return None
    return _normalize(found.get((section.casefold(), name.casefold())))


def adopt_machine_identity(environment, command, env, check=lambda: None, timeout=300):
    """Give a newly created environment this computer's machine identity.

    Called once, while an environment is being created and before anything is
    installed or activated in it. It is refused on an environment that already
    holds activations, because changing the value there is the very thing that
    makes a vendor see a different machine — the point is to stop new
    environments inventing identities, not to rewrite existing ones.

    The value is set through Wine's own registry tooling rather than by editing
    the hive, so a running server cannot overwrite it and a malformed write
    cannot damage the environment.
    """
    from . import core as _core
    environment = Path(environment)
    guard(environment, 'rewrite_identity')
    wanted = host_machine_guid(environment.parent.parent)
    if wanted is None:
        return {'changed': False, 'reason': 'no stable host identity available'}
    if current_machine_guid(environment) == wanted:
        return {'changed': False, 'reason': 'already this computer'}
    before = current_machine_guid(environment)
    # The launcher's own output (Proton and umu messages, then reg's). It holds
    # no vendor or account data, and without it a failure here says only
    # "exit 1".
    log = environment / 'machine-identity.log'
    result = _core.run_process([*command, 'reg', 'add', r'HKLM\Software\Microsoft\Cryptography',
                                '/v', 'MachineGuid', '/t', 'REG_SZ', '/d', wanted, '/f'],
                               env, log, check, timeout)
    if result:
        try:
            tail = [line.strip() for line in log.read_text(errors='replace').splitlines() if line.strip()][-3:]
        except OSError:
            tail = []
        raise core.HostError('Could not give this environment the computer\'s machine identity '
                             '(exit ' + str(result) + ').' + (' ' + ' / '.join(tail) if tail else '')
                             + ' The full output is in ' + str(log) + '.')
    after = current_machine_guid(environment)
    if after == wanted:
        return {'changed': True}
    if before is not None:
        # The environment had an identity and kept it, which is a real failure
        # rather than an environment that has not been initialized yet.
        raise core.HostError('The environment did not take the computer\'s machine identity.')
    # Nothing to read back yet. is_this_computer() reports the outcome later,
    # and protecting an environment surfaces it before any licence depends on it.
    return {'changed': None, 'reason': 'environment has no registry to confirm it in yet'}


def is_this_computer(environment):
    """Does this environment report the machine identity of this computer?

    ``None`` when there is nothing to compare — no registry yet, or no stable
    host identity. Used to surface an environment that invented its own
    identity, which spends a machine against a vendor's per-machine limit.
    """
    environment = Path(environment)
    wanted = host_machine_guid(environment.parent.parent)
    observed = current_machine_guid(environment)
    if wanted is None or observed is None:
        return None
    return observed == wanted
