"""Shared hash-verified downloads and bounded archive extraction.

Callers select trusted artifact descriptors and own installation policy.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import shutil
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit, unquote

from . import core

class Source(NamedTuple):
    """Where a kind of artifact may be downloaded from.

    A recipe author chooses both the URL and the pinned hash, so this is the
    only control deciding whose bytes may later be executed. It is enforced on
    the declared URL and again on every redirect hop. Every built-in source is
    HTTPS-only; the scheme is part of the policy so tests can exercise the
    redirect rules against loopback without a back door in the code under test.
    """
    hosts: tuple
    schemes: tuple = ('https',)
    #: Built-in sources use the scheme's default port. Only the loopback
    #: policy used by the tests names a port at all.
    any_port: bool = False
    #: Whether the declared host is a redirector to a pool of mirrors, which is
    #: how the MSYS2 packages are distributed: one published URL, a different
    #: mirror host on each request, and no list anyone could enumerate. The
    #: scheme, port and credential rules still apply to every hop; only the
    #: host list is relaxed, and only because these artifacts are pinned by
    #: SHA-256 and verified after download, so a substituted mirror cannot
    #: change what gets installed -- it can only fail the check.
    mirrors: bool = False
    # Optional first-request paths; CDN hosts remain redirect-only.
    entry_prefixes: tuple = ()

    def describe(self):
        return ', '.join(self.hosts)

    def at(self, host):
        """The same policy applied to a mirror this source redirected to."""
        return self._replace(hosts=(host,))


#: The only source reachable from a recipe.
MICROSOFT_DOWNLOADS = Source(('download.visualstudio.microsoft.com', 'download.microsoft.com'))
#: Pinned runtime and bridge releases, named by built-in descriptors only.
RUNTIME_RELEASES = Source(
    ('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', 'repo.steampowered.com'),
    entry_prefixes=(
        'https://github.com/Open-Wine-Components/umu-proton/releases/download/',
        'https://github.com/Open-Wine-Components/umu-launcher/releases/download/',
        'https://repo.steampowered.com/steamrt3/images/',
        'https://github.com/oikoaudio/plugg/releases/download/',
    ))
#: Pinned archive-utility packages, named by built-in descriptors only.
ARCHIVE_PACKAGES = Source(('mirror.msys2.org', 'repo.msys2.org'), mirrors=True)


def validate_url(url, source, field='Dependency'):
    """Accept only an allowed scheme and host, with no credentials or fragment."""
    if not isinstance(url, str):
        raise ValueError(field + ' URLs must be text')
    parts = urlsplit(url)
    if parts.scheme not in source.schemes or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError(field + ' URLs must use ' + '/'.join(source.schemes).upper() +
                         ' without credentials or fragments')
    if parts.hostname not in source.hosts:
        raise ValueError(field + ' downloads must use an allowed host: ' + source.describe())
    if parts.port is not None and not source.any_port:
        raise ValueError(field + ' downloads must use the default port')
    return url


def validate_entry_url(url, source):
    validate_url(url, source)
    if source.entry_prefixes:
        parts = urlsplit(url)
        if (not any(url.startswith(prefix) for prefix in source.entry_prefixes)
                or parts.query or '\\' in unquote(parts.path)
                or any(part in ('.', '..') for part in unquote(parts.path).split('/'))):
            raise ValueError('Runtime downloads must start at a supported project release path; CDN URLs are redirect-only')
    return url


def redirect_policy(source, newurl):
    """What a redirect target must satisfy, given where the request started.

    For a mirror pool the host cannot be known in advance, so requiring it to
    be on the list would mean refusing the only URL the project publishes. The
    rest of the policy is unchanged, and the pinned SHA-256 is what actually
    decides whether the bytes are used.
    """
    if not source.mirrors:
        return source
    host = urlsplit(newurl).hostname
    return source.at(host) if host else source


class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-apply the policy to every redirect target.

    urllib follows redirects to any host, and to http and ftp. Validating only
    the declared URL would mean the allowlist governs the first request and
    nothing else, so the same check runs again for each hop.
    """

    def __init__(self, source):
        self.source = source

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            validate_url(newurl, redirect_policy(self.source, newurl))
        except ValueError as exc:
            # The refused response is not handed on, so close it here.
            fp.close()
            raise urllib.error.HTTPError(newurl, code, str(exc), headers, None) from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_verified(url, source, timeout=30):
    """Open a URL that is allowed now and after every redirect."""
    validate_entry_url(url, source)
    opener = urllib.request.build_opener(_AllowedRedirects(source))
    response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'Plugg/0.1'}),
                           timeout=timeout)
    try:
        validate_url(response.geturl(), redirect_policy(source, response.geturl()))
    except ValueError:
        response.close()
        raise
    return response


def fetch(store, asset, report, check, source):
    fingerprint = asset['sha256']
    if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise core.HostError('Dependency requires an exact SHA-256')
    try:
        validate_entry_url(asset['url'], source)
    except ValueError as exc:
        raise core.HostError(str(exc)) from exc
    name = urlsplit(asset['url']).path.rsplit('/', 1)[-1]
    if not name or name in ('.', '..') or '\\' in name or '\0' in name:
        raise core.HostError('Dependency URL must identify a file')
    cache = store.root / 'downloads'
    cache.mkdir(exist_ok=True)
    target = cache / (fingerprint + '-' + name)
    check()
    if target.is_file() and core.digest(target) == fingerprint:
        return target
    # Older installations used the basename alone. Reuse verified bytes while
    # preserving the old cache entry; never return a path another version owns.
    legacy = cache / name
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
        partial = Path(stream.name)
        try:
            if legacy.is_file() and core.digest(legacy) == fingerprint:
                with legacy.open('rb') as source:
                    while block := source.read(1024 * 1024):
                        check()
                        stream.write(block)
            else:
                with open_verified(asset['url'], source) as response:
                    count = 0
                    while block := response.read(1024 * 1024):
                        check()
                        count += len(block)
                        if count > 1024**3:
                            raise core.HostError('Dependency download exceeds the size limit')
                        stream.write(block)
                        report(f'Downloading Windows support · {count // 1048576} MB')
            stream.flush()
            if core.digest(partial) != fingerprint:
                raise core.HostError('Dependency checksum mismatch: ' + name)
            check()
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target


def unpack(archive, destination):
    if archive.name.endswith('.zst'):
        if not shutil.which('zstd'):raise core.HostError('Install the Linux zstd utility to unpack the archive component.')
        with tempfile.TemporaryDirectory() as tmp:
            tar=Path(tmp)/'package.tar'
            with tar.open('wb') as out:
                subprocess.run(['zstd','-q','-d','-c',str(archive)],stdout=out,check=True,timeout=120)
            core.safe_extract(tar,destination)
    else:
        core.safe_extract(archive,destination)


