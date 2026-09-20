"""Installation control plane. Nothing here runs on a DAW audio thread.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
import os
from pathlib import Path
import shlex
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[1]


def plugg_command(*arguments):
    """Run this Plugg as a separate process, from a checkout or an installed package.

    Callers start it in the library directory, never in REPO: for the
    installed package REPO is the system site-packages directory, and
    Proton's container refuses to start in a working directory under /usr.
    The import path is set inside the child rather than through PYTHONPATH,
    so it does not leak into Proton or vendor programs started from there.
    """
    boot = 'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("plugg", run_name="__main__", alter_sys=True)'
    return [sys.executable, '-c', boot, str(REPO), *[str(argument) for argument in arguments]]
TERMINAL = {"ready", "needs_attention", "failed", "cancelled"}
#: Bounds on what a single installer may bring with it.
INSTALLER_FILE_LIMIT = 64
INSTALLER_BYTE_LIMIT = 16 * 1024**3
#: A Unix socket path is capped at 108 bytes including its terminator, and
#: yabridge builds one per plug-in instance out of the published bundle's
#: name. Publishing under a hash kept every name the same short length and
#: made the DAW's plug-in folder unreadable: a host that fails to load one
#: has nothing to show the user but the path, and a folder of hashes tells
#: them nothing about what it found. The budget below is what is actually
#: left for a name, so a name can be used whenever it fits.
SOCKET_PATH_LIMIT = 107
#: The longest file yabridge creates inside the per-plug-in socket directory,
#: with room for an instance counter that will never realistically get there.
LONGEST_SOCKET_FILE = "host_plugin_audio_processor_" + "9" * 6 + ".sock"
#: How a maker's name is written short when it leads a product name.
#:
#: This is knowledge, not a rule. Nothing in a plug-in's metadata says that
#: "Unfiltered Audio" is a brand rather than two ordinary words, and the
#: vendor field is often the distributor — every Unfiltered Audio plug-in
#: here reports "Plugin Alliance". Without the table a maker's products get
#: abbreviated only when they happen to be too long, so "UA Bass Mint" is
#: filed next to "Unfiltered Audio Silo". With it they are written the same
#: way whatever their length. It is a list, and it grows by hand.
BRAND_NAMES = {
    "unfiltered audio": "UA",
    "universal audio": "uaudio",
}
WINE = {
    "id": "wine-11.0-amd64-wow64",
    "url": "https://github.com/Kron4ek/Wine-Builds/releases/download/11.0/wine-11.0-amd64-wow64.tar.xz",
    "sha256": "39574efa1132c3ca0d5c77dd2eddbe4a49cca0d6cc2c290ff4924493a1c40314",
    "source": "https://github.com/Kron4ek/Wine-Builds/releases/tag/11.0",
}


class HostError(Exception):
    pass


class Cancelled(HostError):
    pass


class DuplicateInstaller(HostError):
    """These exact bytes are already here. Whether that is a dead end depends.

    An installation under way has nothing to offer but waiting. A finished one
    can be done over, which is usually why someone is dropping the file a
    second time, so the caller is told which case this is rather than being
    handed the same refusal for both.
    """

    def __init__(self, message, job, replaceable):
        super().__init__(message)
        self.job = job
        self.replaceable = replaceable


class SharedEnvironmentInstaller(HostError):
    """A vendor manager that belongs in the iLok environment, not a new one.

    Softube Central and UA Connect are licensed through iLok. A new environment
    would be another machine to iLok and would lack PACE, so the generic path
    would install something that cannot work. The caller is told where it goes.
    """

    def __init__(self, message, name, recipe, environment):
        super().__init__(message)
        self.name = name
        self.recipe = recipe
        self.environment = environment


#: Installers reviewed for joining the shared iLok environment, by SHA-256.
def shared_environment_installers():
    from . import softube_setup, ua_setup
    known = {softube_setup.INSTALLER_SHA256: ('Softube Central', 'plugg.softube@2')}
    for sha256, _ in ua_setup.VERSIONS.values():
        known[sha256] = ('UA Connect', 'plugg.universal-audio@1')
    return known


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
        json.dump(data, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def pe_machine(path: Path) -> int:
    with path.open("rb") as f:
        head = f.read(64)
        if len(head) < 64 or head[:2] != b"MZ":
            raise HostError("This is not a Windows executable.")
        offset = struct.unpack_from("<I", head, 60)[0]
        if offset > min(path.stat().st_size - 6, 16 * 1024 * 1024):
            raise HostError("The Windows executable header is damaged.")
        f.seek(offset)
        head = f.read(6)
        if head[:4] != b"PE\0\0":
            raise HostError("The Windows executable header is damaged.")
        return struct.unpack_from("<H", head, 4)[0]


def installer_type(path: Path) -> str:
    if not path.is_file():
        raise HostError("Choose a Windows .exe or .msi installer file.")
    if path.suffix.lower() == ".msi":
        with path.open("rb") as f:
            if f.read(8) != bytes.fromhex("d0cf11e0a1b11ae1"):
                raise HostError("This file does not contain an MSI installer.")
        return "msi"
    if path.suffix.lower() != ".exe":
        raise HostError("Choose a Windows .exe or .msi installer file.")
    if pe_machine(path) not in (0x8664, 0x14C):
        raise HostError("This installer targets an unsupported Windows architecture.")
    return "exe"


@contextlib.contextmanager
def lock(path: Path, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise HostError("This operation is already running.") from None
        yield


def worker_running(path: Path):
    """Whether a process still holds this lock, without disturbing it."""
    try:
        handle = path.open('r')
    except OSError:
        return False
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        handle.close()


def module_runner(root: Path) -> Path:
    """The library's way into this package, wherever the package is right now.

    Launchers written into an environment outlive the code that wrote them. One
    that names a checkout breaks when the checkout moves, and the vendor's
    helper then simply fails to open. They call this instead, and it is
    rewritten each time the library is opened, so a moved or reinstalled
    package is picked up the next time the app runs.
    """
    runner = root / "bin" / "python-module"
    content = ("#!/bin/sh\n# Written by Plugg each time the library is opened.\n"
               "PYTHONPATH=" + shlex.quote(str(REPO)) + "${PYTHONPATH:+:$PYTHONPATH} exec "
               + shlex.quote(sys.executable) + ' -m "$@"\n')
    if not runner.is_file() or runner.read_text() != content:
        runner.parent.mkdir(parents=True, exist_ok=True)
        temporary = runner.with_name(".python-module-" + uuid.uuid4().hex)
        temporary.write_text(content)
        temporary.chmod(0o700)
        os.replace(temporary, runner)
    return runner


def write_module_launcher(launcher: Path, module: str, directory: Path):
    """A launcher in an environment that runs one of this package's modules on it."""
    directory = Path(directory)
    library = directory.parent.parent
    if (library / "settings.json").is_file():
        command = [str(module_runner(library)), module, str(directory)]
    else:
        # Not inside a library (a harness's scratch environment): nothing can
        # repair the launcher later, so it names the package directly.
        command = ["env", "PYTHONPATH=" + str(REPO), sys.executable, "-m", module, str(directory)]
    launcher.write_text("#!/bin/sh\nset -eu\nexec " + shlex.join(command) + "\n")
    launcher.chmod(0o700)


def default_bridge_directory():
    """A checkout's own build first, then the one an installed package ships."""
    candidates = [REPO / "bundle/bridge", Path(sys.prefix) / "lib/plugg/bridge",
                  Path("/usr/lib/plugg/bridge")]
    from . import bridge_bundle
    for candidate in candidates:
        if (candidate / "build.json").is_file():
            try:
                bridge_bundle.inspect(candidate)
            except HostError:
                # A stale build, such as one from before the rename, is skipped
                # rather than chosen and then refused.
                continue
            return candidate
    return candidates[0]


class Store:
    def __init__(self, root: Path | None = None, publication: Path | None = None, bridge_dir: Path | None = None):
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        default = data_home / "plugg"
        self.root = (root or default).expanduser().resolve()
        settings = self.root / "settings.json"
        if settings.exists():
            saved = json.loads(settings.read_text())
            if publication and str(publication.expanduser().resolve()) != saved["publication"]:
                raise HostError("This library already has a different publication location.")
            self.bridge_selection = saved.get("bridge")
            if bridge_dir and (not self.bridge_selection or
                               str(bridge_dir.expanduser().resolve()) != self.bridge_selection["directory"]):
                raise HostError("This library already has a bridge selection. Use a new library for another bridge build.")
            self.publication = Path(saved["publication"])
        else:
            self.publication = (publication or Path.home() / ".vst3/plugg").expanduser().resolve()
            from . import bridge_bundle
            self.bridge_selection = bridge_bundle.inspect(bridge_dir) if bridge_dir else None
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            saved = {"publication": str(self.publication), "schema": 1}
            if self.bridge_selection:
                saved["bridge"] = self.bridge_selection
            atomic_json(settings, saved)
        module_runner(self.root)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, installer TEXT NOT NULL,
                  kind TEXT NOT NULL, hash TEXT NOT NULL, status TEXT NOT NULL,
                  message TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                  cancel INTEGER NOT NULL DEFAULT 0, pid INTEGER, env_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS archived_jobs (job_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS plugins (
                  id TEXT PRIMARY KEY, env_id TEXT NOT NULL, name TEXT NOT NULL,
                  module TEXT NOT NULL, hash TEXT NOT NULL, status TEXT NOT NULL,
                  metadata TEXT NOT NULL, publication TEXT, message TEXT NOT NULL);
            """)

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "library.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def jobs(self):
        with self.db() as db:
            return [dict(x) for x in db.execute("SELECT jobs.*, EXISTS(SELECT 1 FROM archived_jobs WHERE job_id=jobs.id) AS archived FROM jobs ORDER BY created DESC")]

    def archive(self, job_id, archived=True):
        with self.db() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise HostError('Installation not found.')
            if archived and row['status'] not in TERMINAL:
                raise HostError('Wait for this installation to finish before archiving it.')
            if archived:
                db.execute('INSERT OR IGNORE INTO archived_jobs VALUES(?)', (job_id,))
            else:
                db.execute('DELETE FROM archived_jobs WHERE job_id=?', (job_id,))

    def plugins(self):
        with self.db() as db:
            return [dict(x) for x in db.execute("SELECT * FROM plugins ORDER BY name")]

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HostError("Installation not found.")
        return dict(row)

    def update(self, job_id, status, message, **extra):
        allowed = {"pid", "cancel"}
        if not set(extra) <= allowed:
            raise ValueError("Invalid job field")
        pairs = {"status": status, "message": message, "updated": time.time(), **extra}
        with self.db() as db:
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in pairs) + " WHERE id=?", (*pairs.values(), job_id))

    def cancelled(self, job_id):
        if self.job(job_id)["cancel"]:
            raise Cancelled("Installation cancelled. Your other plug-ins are unchanged.")

    def cancel(self, job_id):
        """Ask a running worker to stop, and settle the job if none is running.

        The flag on its own is a message to a process. A job whose worker never
        started, or died before claiming it, has no reader — so raising the
        flag left the row waiting for a reply that could not come, and both the
        Cancel button and the command did nothing at all, twice, quietly.

        A worker holds the job's lock for as long as it owns the job, so a lock
        that is free is the evidence that nobody is listening.
        """
        with self.db() as db:
            db.execute("UPDATE jobs SET cancel=1 WHERE id=? AND status NOT IN ('ready','failed','cancelled','needs_attention')", (job_id,))
        if self.job(job_id)['status'] in TERMINAL or worker_running(self.root / 'jobs' / job_id / 'job.lock'):
            return
        self.update(job_id, 'cancelled', 'Cancelled before it started. Nothing was installed.', pid=None)

    def duplicate(self, fingerprint, replace=False):
        """Refuse these exact bytes if the library already has them.

        The same installer arriving twice is not a second product. It is the
        same one, and taking it in again costs an environment, a download, and
        for a vendor installer the vendor's slot -- which is how one impatient
        double-drop turns into a failure that has to be cleaned up by hand.

        The test is the content hash and never the file name, because the case
        that must keep working is the upgrade: next year's installer arrives
        under exactly the name this one had. Different bytes are a different
        product as far as this is concerned, whatever they are called.

        Only two states count. An installation still under way is the case that
        actually happens, because that is the wait during which someone tries
        again. A finished one that the library still offers is the other. A
        failed attempt must stay re-addable, since retrying is the whole point,
        and so must one that was archived, since archiving is how you say you
        want it out of the way.

        Replacing is doing the finished one over: the old installation is
        archived and the plug-ins it published are retired, so the new one has
        a clear field. It never touches the vendor's own files or activations,
        and the archived installation keeps everything it had.
        """
        for job in self.jobs():
            if job['hash'] != fingerprint or job['archived']:
                continue
            if job['status'] not in TERMINAL:
                raise DuplicateInstaller(
                    'This installer is already being added. Its progress is shown under the drop '
                    'area; wait for it to finish, or cancel it there.', job, replaceable=False)
            if job['status'] != 'ready':
                continue
            if not replace:
                raise DuplicateInstaller(
                    '"' + job['name'] + '" was installed from this exact file already.',
                    job, replaceable=True)
            self.archive(job['id'])
            try:
                forget_environment(self, job['env_id'])
            except HostError:
                pass  # Nothing published from it; there is nothing to stand aside.

    def discard(self, job_id):
        """Forget an attempt, and the installer copy the attempt was keeping.

        A failed setup was kept because it pointed at an environment that might
        already hold installed or activation data, and dropping the record
        silently would have orphaned it. The environments view shows that
        environment directly now — its size, and a flag saying nothing refers
        to it any more — so the pointer has become the only thing standing
        between someone and a window with nothing dead in it.

        The environment is not touched. What goes is this record and the job's
        own directory, which holds a copy of the installer that the original
        file on disk already is.
        """
        import shutil
        job = self.job(job_id)
        if job['status'] not in TERMINAL:
            raise HostError('Cancel this installation before discarding it.')
        if worker_running(self.root / 'jobs' / job_id / 'job.lock'):
            raise HostError('Something is still working on this installation.')
        with self.db() as db:
            db.execute('DELETE FROM archived_jobs WHERE job_id=?', (job_id,))
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
        directory = self.root / 'jobs' / job_id
        if directory.resolve().parent == (self.root / 'jobs').resolve():
            shutil.rmtree(directory, ignore_errors=True)
        return {'job': job_id, 'environment': job['env_id']}

    def ingest(self, source: Path, replace=False):
        if source.suffix.lower() == ".vst3":
            from .standalone import ingest
            return ingest(self, source)
        source = source.expanduser().resolve()
        kind = installer_type(source)
        if kind == "exe":
            shared = shared_environment_installers().get(digest(source))
            if shared:
                from . import ilok_setup
                environment = ilok_setup.current(self)
                name, recipe = shared
                if environment is None or not environment.is_dir():
                    raise HostError(name + ' is licensed through iLok, so it goes into the iLok environment, '
                                    'and this library has none yet. Create it first with '
                                    '"plugg ilok create PACE.msi", then add ' + name + ' again.')
                raise SharedEnvironmentInstaller(name + ' goes into your iLok environment, next to PACE.',
                                                 name, recipe, environment)
        job_id = uuid.uuid4().hex
        directory = self.root / "jobs" / job_id
        directory.mkdir(parents=True, mode=0o700)
        # Preserve the original basename: split installers can derive the names
        # of their external data files from their executable's name.
        payload = directory / "payload"
        payload.mkdir(mode=0o700)
        dest = payload / source.name
        try:
            inputs = [source]
            if kind == "exe":
                # The user selects an extracted installer folder. Payload names
                # vary, so include all adjacent .bin files, including split parts.
                inputs.extend(sorted(x for x in source.parent.iterdir()
                                     if x.suffix.lower() == ".bin"))
            if len(inputs) > INSTALLER_FILE_LIMIT:
                raise HostError("This folder holds more installer data files than a single installer should. "
                                "Extract the installer into a folder of its own, then add it again.")
            files = []
            copied_bytes = 0
            for item in inputs:
                if item.is_symlink() or not item.is_file():
                    raise HostError("Installer data must be regular files. Extract the .exe and .bin files together, then add the installer again.")
                # Check before writing: a sparse file costs nothing to offer and
                # everything to copy, so the size is charged from its own header.
                copied_bytes += item.stat().st_size
                if copied_bytes > INSTALLER_BYTE_LIMIT:
                    raise HostError("This installer and its data files exceed the supported size.")
                copied = payload / item.name
                shutil.copyfile(item, copied)
                files.append({"name": item.name, "sha256": digest(copied)})
            # Validate the copy, so a changed input never silently becomes executable.
            installer_type(dest)
            # The first moment these bytes can be identified, and before any
            # environment, download or vendor slot is spent on them.
            self.duplicate(files[0]["sha256"], replace)
            from . import recipes, vendors, helper_recipes
            selected_helper = helper_recipes.match(files[0]["sha256"])
            known_helper = recipes.recognized(files[0]["sha256"])
            if selected_helper and kind != "exe":
                raise HostError("Helper recipes currently support EXE installers only.")
            if known_helper and selected_helper and not helper_recipes.replaces_builtin(selected_helper, files[0]['sha256']):
                raise HostError("This installer already has a built-in helper adapter; a local recipe cannot replace it implicitly.")
            if known_helper and any(v['recipe'] == 'klevgrand' for v in vendors.cards(self)):
                raise HostError("Klevgrand is already configured. Use Open Helper on its vendor card.")
            if not known_helper and "klevgrand" in source.name.lower() and "helper" in source.name.lower():
                raise HostError("This Klevgrand Helper installer version has not been validated for automatic setup yet.")
            if selected_helper:
                atomic_json(directory / "helper-recipe.json", selected_helper)
            atomic_json(directory / "installer-files.json", {"schema": 1, "files": files})
            now = time.time()
            with self.db() as db:
                db.execute("INSERT INTO jobs(id,name,installer,kind,hash,status,message,created,updated,env_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (job_id, source.stem, str(dest), kind, files[0]["sha256"], "queued", "Preparing installation", now, now, job_id))
        except Exception:
            shutil.rmtree(directory)
            raise
        return job_id

    def start(self, job_id, rescan=False):
        self.job(job_id)
        log = self.root / "jobs" / job_id / "worker.log"
        with log.open("ab", buffering=0) as out:
            args = plugg_command("--data", self.root, "worker", job_id)
            if rescan:
                args.append("--rescan")
            proc = subprocess.Popen(args, cwd=self.root, stdout=out, stderr=out, start_new_session=True)
        return proc.pid

    def prefix(self, job_id):
        return self.root / "environments" / self.job(job_id)["env_id"] / "prefix"

    def bridge_directory(self):
        return Path(self.bridge_selection['directory']) if self.bridge_selection else default_bridge_directory()

    def bridge(self):
        """The bridge release new bundles link to, owned by this library."""
        from . import bridge_bundle
        return bridge_bundle.install_release(self.bridge_source(), self.root / "bridge-releases")

    def bridge_source(self):
        """The build a release is made from, checked against what was selected."""
        b = self.bridge_directory()
        if self.bridge_selection:
            from . import bridge_bundle
            bridge_bundle.inspect(b, self.bridge_selection['manifest_sha256'])
            return b
        required = ["libyabridge-vst3.so", "libyabridge-chainloader-vst3.so", "yabridge-host.exe", "yabridge-host.exe.so", "plugg-scan"]
        if not all((b / x).is_file() for x in required):
            raise HostError("The native bridge is missing. For a new library, select a built bridge with --bridge-dir; checkout builds use scripts/build-bridge.sh.")
        return b


def forget_plugin(store, identity):
    """Retire a published plug-in that is no longer installed.

    Publishing refuses to offer two plug-ins with the same class identity, which
    is what stops an accidental duplicate. Without a way to retire a record, that
    same check permanently blocks reinstalling a product the user removed
    themselves: the library goes on believing it is ready, and the vendor's own
    uninstaller has no way to say otherwise.

    This removes it from the directory the DAW scans and marks the record, so
    the product can be installed again later. The built bundle is kept, so the
    removal can be inspected or undone by republishing.
    """
    with lock(store.root / "publication.lock"):
        with store.db() as db:
            row = db.execute("SELECT * FROM plugins WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise HostError("No such plug-in in this library: " + identity)
            published = row["publication"]
            if published:
                target = Path(published)
                # Only ever remove a link this library created, never a real file.
                if target.is_symlink():
                    target.unlink()
                elif target.exists():
                    raise HostError("The publication path is not a managed link; leaving it alone: " + published)
            db.execute("UPDATE plugins SET status=?, message=? WHERE id=?",
                       ("removed", "Removed from your DAW. Install it again to bring it back.", identity))
    return {"id": identity, "name": row["name"], "environment": row["env_id"], "unpublished": bool(published)}


def forget_environment(store, env_id):
    """Retire every plug-in published from one environment."""
    found = [p for p in store.plugins() if p["env_id"] == env_id and p["status"] != "removed"]
    if not found:
        raise HostError("No published plug-ins remain for this environment: " + env_id)
    return [forget_plugin(store, item["id"]) for item in found]


def reconcile_journalled_jobs(store, journal_name, message, *, kind=None):
    """Mark interrupted operations using their lock, without replay or cleanup."""
    changed = 0
    for job in store.jobs():
        if (kind is not None and job['kind'] != kind) or job['status'] in TERMINAL:
            continue
        directory = store.root / 'jobs' / job['id']
        if not (directory / journal_name).is_file():
            continue
        try:
            with lock(directory / 'job.lock', blocking=False):
                current = store.job(job['id'])
                if current['status'] in TERMINAL:
                    continue
                store.update(job['id'], 'needs_attention', message, pid=None)
                changed += 1
        except HostError:
            # Another worker owns the operation. A PID alone is not evidence.
            continue
    return changed


def verify_installer(job):
    installer = Path(job["installer"])
    if digest(installer) != job["hash"]:
        raise HostError("The stored installer has changed. Add the original installer again.")
    if installer.parent.name != "payload":
        return  # Jobs created before companion-file support stored a single file.
    manifest = installer.parent.parent / "installer-files.json"
    if not manifest.is_file():
        raise HostError("The installer file inventory is missing. Add the original installer again.")
    data = json.loads(manifest.read_text())
    if data.get("schema") != 1 or not data.get("files"):
        raise HostError("The installer file inventory is damaged. Add the original installer again.")
    for entry in data["files"]:
        name = entry["name"]
        if not name or Path(name).name != name or name in (".", ".."):
            raise HostError("The installer file inventory contains an invalid path.")
        path = installer.parent / name
        if path.is_symlink() or not path.is_file() or digest(path) != entry["sha256"]:
            raise HostError(f"Installer file {name} is missing or changed. Add the original installer again.")


def safe_extract(archive: Path, destination: Path, check=lambda: None):
    """Use Python's data filter; reject devices and any escaping path/link.

    Members are read one at a time so the limits are reached before the archive
    has been decompressed, not after: reading the whole member list first means
    a compressed bomb is paid for in full before it can be refused.
    """
    with tarfile.open(archive, "r:*") as tar:
        count = 0
        total = 0
        for member in tar:
            check()
            count += 1
            total += member.size
            if count > 100000 or total > 4 * 1024**3:
                raise HostError("The runtime archive exceeds the supported size.")
            tar.extract(member, destination, filter="data")


def provision_wine(store: Store, report=lambda _: None, check=lambda: None):
    target = store.root / "runtimes" / WINE["id"]
    with lock(store.root / "runtime.lock"):
        manifest = target / "runtime.json"
        if manifest.exists():
            data = json.loads(manifest.read_text())
            binary = target / data["wine"]
            if data["archive_sha256"] != WINE["sha256"] or not binary.is_file():
                raise HostError("The managed runtime is damaged. Restore it before installing.")
            return binary
        cache = store.root / "downloads"
        cache.mkdir(exist_ok=True)
        archive = cache / (WINE["id"] + ".tar.xz")
        if not archive.exists() or digest(archive) != WINE["sha256"]:
            partial = archive.with_suffix(".part")
            from . import artifacts
            # GitHub serves release assets from a separate download host, so the
            # runtime source names both; every redirect hop is checked again.
            try:
                with artifacts.open_verified(WINE["url"], artifacts.RUNTIME_RELEASES) as response, partial.open("wb") as out:
                    total = int(response.headers.get("Content-Length", "0"))
                    count = 0
                    while chunk := response.read(1024 * 1024):
                        check()
                        count += len(chunk)
                        if count > 512 * 1024**2:
                            raise HostError("The runtime download exceeds its size limit.")
                        out.write(chunk)
                        report(f"Downloading Windows support · {count // 1048576} MB" + (f" of {total // 1048576} MB" if total else ""))
                if digest(partial) != WINE["sha256"]:
                    raise HostError("Runtime download verification failed. Please try again.")
                os.replace(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
        check()
        target.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=target.parent) as tmp:
            stage = Path(tmp)
            report("Unpacking Windows support")
            safe_extract(archive, stage)
            candidates = list(stage.glob("*/bin/wine"))
            if len(candidates) != 1:
                raise HostError("The runtime package has an unexpected layout.")
            rel = str(candidates[0].relative_to(stage))
            atomic_json(stage / "runtime.json", {"provider": "wine", "id": WINE["id"], "archive_sha256": WINE["sha256"], "wine": rel, "source": WINE["source"]})
            os.rename(stage, target)
        return target / rel


def adopt_installed_helper(store, job):
    """Give a vendor's own app, left behind by its installer, a helper card.

    Some installers are their vendor's manager: Kilohearts Installer installs
    itself into the environment and is how products are added or updated
    later. When a program there carries the installer's own name, it is that
    app. Anything less certain is left for the person to choose.
    """
    from . import vendors
    base = re.sub(r"\s*[\[(].*$", "", job["name"]).strip().casefold()
    if not base:
        return None
    try:
        directory = store.root / "environments" / job["env_id"]
        matches = [c for c in vendors.helper_candidates(directory) if Path(c).stem.casefold() == base]
        if len(matches) != 1:
            return None
        return vendors.adopt_helper(store, job["env_id"], matches[0], Path(matches[0]).stem)
    except (HostError, OSError, ValueError):
        return None


def runtime_label(session):
    """What an environment runs on, in words: the Proton build and any overlay."""
    proton = Path(session.get("proton", "")).parent.name
    return "UMU-Proton-10.0-4" + (" (" + "-".join(proton.split("-")[3:5]) + ")" if proton.startswith("proton-10.0-4-plugg-") else "")


def runtime_env(prefix: Path, wine: Path):
    env = os.environ.copy()
    for key in ("WINEPREFIX", "WINELOADER", "WINESERVER", "WINEDLLPATH", "WINEDLLOVERRIDES", "WINEARCH", "WAYLAND_DISPLAY", "LD_PRELOAD"):
        env.pop(key, None)
    env.update(WINEPREFIX=str(prefix), WINELOADER=str(wine), WINESERVER=str(wine.parent / "wineserver"), WINEDEBUG="-all", WINEDLLOVERRIDES="winemenubuilder.exe=d")
    return env


def create_launcher(prefix: Path, wine: Path):
    """A fixed per-environment launch target used by the patched native bridge."""
    script = prefix.parent / "launch-wine"
    script.write_text("#!/bin/sh\n" +
                      "unset WINEARCH WINEDLLPATH LD_PRELOAD WAYLAND_DISPLAY\n" +
                      f"export WINEPREFIX={shlex.quote(str(prefix))}\n" +
                      f"export WINELOADER={shlex.quote(str(wine))}\n" +
                      f"export WINESERVER={shlex.quote(str(wine.parent / 'wineserver'))}\n" +
                      "export WINEDLLOVERRIDES='winemenubuilder.exe=d'\n" +
                      f"exec {shlex.quote(str(wine))} \"$@\"\n")
    script.chmod(0o700)
    (prefix / ".plugg-runtime").write_text(str(script) + "\n")


def run_process(args, env, log: Path, check=lambda: None, timeout=3600, cwd=None):
    """No shell, bounded runtime, a process group private to this operation."""
    with log.open("ab", buffering=0) as out:
        proc = subprocess.Popen([str(x) for x in args], env=env, stdout=out, stderr=out, start_new_session=True, cwd=cwd)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                check()
                if time.monotonic() - started > timeout:
                    raise HostError("This operation took too long. See installation details.")
                time.sleep(0.15)
            return proc.returncode
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()


def discover(prefix: Path):
    """Bound discovery to the managed drive; do not follow directory symlinks."""
    drive = (prefix / "drive_c").resolve()
    result = []
    seen = set()
    for parent, dirs, files in os.walk(drive, followlinks=False):
        dirs[:] = [x for x in dirs if x.lower() not in {"windows", "$recycle.bin"} and not (Path(parent) / x).is_symlink()]
        for name in files:
            if not name.lower().endswith(".vst3"):
                continue
            path = Path(parent) / name
            if path.is_symlink() or not path.resolve().is_relative_to(drive):
                continue
            if path in seen:
                continue
            seen.add(path)
            try:
                arch = pe_machine(path)
            except HostError:
                continue
            result.append({"path": path, "name": path.stem, "machine": arch, "hash": digest(path)})
    return result


def make_bundle(store: Store, module: Path, dest: Path):
    bridge = store.bridge()
    native = dest / "Contents/x86_64-linux"
    windows = dest / "Contents/x86_64-win"
    native.mkdir(parents=True)
    windows.mkdir()
    # The DLL and Linux proxy need corresponding basenames.
    shutil.copy2(bridge / "libyabridge-chainloader-vst3.so", native / (dest.stem + ".so"))
    (native / ".plugg-managed").write_text("1\n")
    for name in ("libyabridge-vst3.so", "yabridge-host.exe", "yabridge-host.exe.so"):
        (native / name).symlink_to(bridge / name)
    (windows / dest.name).symlink_to(module)
    if module.parent.name == "x86_64-win" and module.parent.parent.name == "Contents":
        resources = module.parent.parent / "Resources"
        if resources.is_dir():
            (dest / "Contents/Resources").symlink_to(resources)
    # Do not copy moduleinfo.json: Windows and Linux class-ID byte order differs.
    return native / (dest.stem + ".so")


def probe(store: Store, module: Path, job_id: str):
    scanroot = store.root / "scans"
    scanroot.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scanroot) as tmp:
        native = make_bundle(store, module, Path(tmp) / "ph-scan.vst3")
        output = Path(tmp) / "result.json"
        log = store.root / "jobs" / job_id / "scan.log"
        # Metadata is loaded in a disposable native process and a Wine host.
        env = os.environ.copy()
        env.pop("WINEPREFIX", None)
        rc = run_process([store.bridge() / "plugg-scan", native, output], env, log, lambda: store.cancelled(job_id), timeout=45)
        if rc != 0 or not output.exists():
            raise HostError("The plug-in did not pass its discovery check. It may need activation; see scan details.")
        data = json.loads(output.read_text())
        if not data.get("classes"):
            raise HostError("No audio plug-in classes were found in this module.")
        return data


def socket_directory():
    """Where the bridge puts its sockets, matching the patched yabridge build."""
    override = os.environ.get("YABRIDGE_TEMP_DIR")
    return Path(override) if override else Path("/dev/shm") / ("plugg-" + str(os.getuid()))


def name_budget(directory=None):
    """How many characters a published bundle's name may use.

    Derived rather than guessed: the whole socket path is the temporary
    directory, yabridge's own prefix, the bundle name, a random suffix and
    the longest socket file it creates. Whatever is left over is the name.
    """
    directory = str(directory or socket_directory())
    overhead = len(directory) + len("/yabridge-") + len("-") + 8 + len("/") + len(LONGEST_SOCKET_FILE)
    return SOCKET_PATH_LIMIT - overhead


def readable_name(name, identity, taken=(), budget=None, vendor=None):
    """A bundle name a person can recognize, or a hash when one is impossible.

    Plug-in names come from vendors, so they contain anything at all. What
    survives here is what is safe in a path and legible in a DAW's plug-in
    list; a name that cannot be made to fit, or that something else already
    answers to, keeps enough of itself to be recognized and takes a short
    piece of the identity to stay unique.
    """
    budget = name_budget() if budget is None else budget
    fallback = "ph-" + identity

    def tidy(text):
        text = "".join(character if character.isalnum() or character in " -_.()&+" else " "
                       for character in str(text or ""))
        return " ".join(text.split()).strip(" .")

    cleaned = tidy(name)
    if not cleaned or budget < len(fallback):
        return fallback
    # A maker who puts their name on every product says it once, short, and
    # says it the same way whether or not that product's name is long: "UA
    # Silo" belongs beside "UA Bass Mint", not beside "Unfiltered Audio Silo".
    words = cleaned.split(' ')
    for brand, short in sorted(BRAND_NAMES.items(), key=lambda item: -len(item[0])):
        maker = brand.split(' ')
        if (len(words) > len(maker)
                and [word.casefold() for word in words[:len(maker)]] == maker):
            words = [short] + words[len(maker):]
            cleaned = " ".join(words)
            break
    else:
        # Failing a known brand, the vendor's own name leading the product is
        # the same situation and can be abbreviated the same way.
        maker = tidy(vendor).split(' ') if tidy(vendor) else []
        if (len(maker) > 1 and len(words) > len(maker)
                and [word.casefold() for word in words[:len(maker)]] == [w.casefold() for w in maker]):
            words = ["".join(word[0] for word in maker).upper()] + words[len(maker):]
            cleaned = " ".join(words)
    if len(cleaned) <= budget and cleaned not in taken:
        return cleaned
    # Shorten the front, never the end. A long plug-in name is usually the
    # maker followed by the product, and the product is the half a person
    # recognizes: "Unfiltered Audio Bass Mint" wants to become "UA Bass
    # Mint", not "Unfiltered Audio Bass", which is a different plug-in.
    words = cleaned.split(' ')
    for keep in range(2, len(words)):
        initials = "".join(word[0] for word in words[:-keep])
        candidate = " ".join([initials] + words[-keep:]).strip()
        if len(candidate) <= budget and candidate not in taken:
            return candidate
    # Two words or fewer, so there is no maker to abbreviate away. Drop from
    # the end rather than cutting through a word.
    breaks = [index for index, character in enumerate(cleaned) if character in " _-"]
    for cut in reversed(breaks):
        candidate = cleaned[:cut].strip(" ._-")
        if candidate and len(candidate) <= budget and candidate not in taken:
            return candidate
    # Nothing legible survives a word boundary: keep the front, which is the
    # part that identifies it, and spend the tail on being unique.
    suffix = "-" + identity[:4]
    for width in range(budget - len(suffix), 0, -1):
        candidate = cleaned[:width].strip(" ._-") + suffix
        if len(candidate) <= budget and candidate not in taken:
            return candidate
    return fallback


def publish(store: Store, item, job_id, metadata, environment=None, identity=None):
    environment = environment or job_id
    identity = identity or hashlib.sha256((job_id + "\0" + str(item["path"])).encode()).hexdigest()[:20]
    with lock(store.root / "publication.lock"):
        # Under the lock: two publications must not pick the same name.
        taken = {Path(row["publication"]).stem for row in store.plugins()
                 if row["status"] != "removed" and row["id"] != identity}
        maker = next((x.get("vendor") for x in metadata["classes"] if x.get("vendor")), None)
        target = store.publication / (readable_name(item["name"], identity, taken, vendor=maker) + ".vst3")
        # Prevent ambiguous duplicate original IDs within this managed library.
        newids = {x["id"] for x in metadata["classes"]}
        for existing in store.plugins():
            if existing["id"] != identity and existing["status"] == "ready":
                oldids = {x["id"] for x in json.loads(existing["metadata"])["classes"]}
                if oldids & newids:
                    raise HostError(f"{existing['name']} is already in your managed library. Updates are not yet supported by this prototype.")
        store.publication.mkdir(parents=True, exist_ok=True)
        bundles = store.root / "bundles"
        bundles.mkdir(exist_ok=True)
        complete = bundles / target.name
        manifest = {"id": identity, "environment": environment, "module_sha256": item["hash"], "metadata": metadata}
        if complete.exists():
            saved = complete / "plugg.json"
            previous = json.loads(saved.read_text()) if saved.is_file() else {}
            # A bundle kept from an installation that was since retired still
            # holds the good name. Nothing publishes it any more — `taken`
            # covers the ones that do — so it steps aside under its own id
            # rather than making the reinstalled plug-in wear a suffix.
            if previous.get("id") and previous["id"] != identity:
                retired = bundles / ("ph-" + previous["id"] + ".vst3")
                if retired.exists():
                    shutil.rmtree(retired)
                os.rename(complete, retired)
        if complete.exists():
            saved = complete / "plugg.json"
            previous = json.loads(saved.read_text()) if saved.is_file() else {}
            # Vendor/version enrichment must not require republishing an unchanged
            # module. The original manifest remains the publication-time snapshot.
            same_module = all(previous.get(key) == manifest[key]
                              for key in ("id", "environment", "module_sha256"))
            previous_ids = {x["id"] for x in previous.get("metadata", {}).get("classes", [])}
            if not same_module or previous_ids != newids:
                raise HostError("This installed module changed. In-place updates are not yet supported.")
        else:
            # Nothing incomplete is ever placed in a directory scanned by the DAW.
            with tempfile.TemporaryDirectory(prefix=".publish-", dir=bundles) as tmp:
                staged = Path(tmp) / target.name
                make_bundle(store, item["path"], staged)
                atomic_json(staged / "plugg.json", manifest)
                os.rename(staged, complete)
        if target.is_symlink() or target.exists():
            if not target.is_symlink() or target.resolve() != complete:
                raise HostError("The publication path is occupied by an unmanaged file.")
        else:
            # Creating one symlink publishes the already complete bundle atomically.
            target.symlink_to(complete, target_is_directory=True)
        # A plug-in published under an older name leaves that link behind, and
        # the DAW would go on scanning it. The bundle it pointed at is kept.
        for row in store.plugins():
            if row["id"] != identity or row["publication"] == str(target):
                continue
            stale = Path(row["publication"])
            if stale.is_symlink() and stale.parent == store.publication:
                stale.unlink()
        # If we were interrupted after the rename, retrying repairs the DB record.
        with store.db() as db:
            db.execute("INSERT OR REPLACE INTO plugins VALUES(?,?,?,?,?,?,?,?,?)", (identity, environment, item["name"], str(item["path"]), item["hash"], "ready", json.dumps(metadata), str(target), "Available to your DAW"))
    return identity


def rename_publications(store: Store, apply=False):
    """Re-publish anything whose name is not what it would be named today.

    That covers a library published under the old hashed scheme, and equally
    one published before the shortening rule was any good, so running it
    again after an improvement is the way to pick that improvement up.

    Nothing is renamed in place and nothing is deleted: a new bundle is built
    beside the old one and the DAW's link is moved to it, so the previous
    bundle remains under `bundles/` and the change can be undone by pointing
    the link back. The plug-in's class identities do not change, which is what
    a project uses to find it again; the path does, so expect a rescan.
    """
    planned = []
    with lock(store.root / "publication.lock"):
        live = [row for row in store.plugins() if row["status"] != "removed"]
        taken = {Path(row["publication"]).stem for row in live}
        budget = name_budget()
        # A name that fits is claimed before any shortened one is considered,
        # so a plug-in never loses its own name to something else's truncation.
        order = sorted(live, key=lambda item: (len(item["name"]) > budget, item["name"].casefold()))
        for row in order:
            current = Path(row["publication"])
            taken.discard(current.stem)
            classes = json.loads(row["metadata"]).get("classes", [])
            maker = next((x.get("vendor") for x in classes if x.get("vendor")), None)
            wanted = readable_name(row["name"], row["id"], taken, vendor=maker)
            taken.add(wanted)
            if wanted == current.stem:
                continue
            planned.append({"id": row["id"], "name": row["name"],
                            "from": str(current), "to": str(store.publication / (wanted + ".vst3"))})
        if not apply:
            return planned
        record = store.root / "migration-backups" / "publication-names.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(record, {"schema": 1, "renames": planned})
        bundles = store.root / "bundles"
        done = []
        for item in planned:
            row = next(x for x in store.plugins() if x["id"] == item["id"])
            module = Path(row["module"])
            if not module.exists():
                raise HostError("Cannot rename " + row["name"] + ": its module is missing. "
                                "Nothing has been changed for it.")
            target = Path(item["to"])
            complete = bundles / target.name
            if not complete.exists():
                with tempfile.TemporaryDirectory(prefix=".publish-", dir=bundles) as tmp:
                    staged = Path(tmp) / target.name
                    make_bundle(store, module, staged)
                    previous = Path(item["from"]).resolve() / "plugg.json"
                    shutil.copy2(previous, staged / "plugg.json")
                    os.rename(staged, complete)
            if not (target.is_symlink() or target.exists()):
                target.symlink_to(complete, target_is_directory=True)
            old = Path(item["from"])
            if old.is_symlink() and old.parent == store.publication:
                old.unlink()
            with store.db() as db:
                db.execute("UPDATE plugins SET publication=? WHERE id=?", (str(target), item["id"]))
            done.append(item)
        atomic_json(record, {"schema": 1, "renames": done, "applied": True})
    return done


BRIDGE_LINKS = ("libyabridge-vst3.so", "yabridge-host.exe", "yabridge-host.exe.so")


def _repoint(link: Path, target: Path):
    """Replace a symlink in one step, so a DAW scanning it never finds it missing."""
    temporary = link.with_name(".relink-" + uuid.uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def relink_publications(store: Store, apply=False):
    """Move published bundles onto links the library itself owns.

    A bundle reaches outside itself twice: the DAW's link to it, and its links
    to the bridge. Bundles published before the library kept its own bridge
    releases link into whichever build directory was current, usually a
    checkout, and the DAW's link may go through the prototype's data path.
    Moving either directory breaks every such plug-in at once, and the DAW
    says only that it failed to initialize.

    Each bundle keeps the exact build it links to now: that build's files are
    copied into a library release, and only then is the link moved. A bundle
    whose bridge cannot be found is reported, not guessed at; rebuilding it
    against today's bridge is a separate decision. Links are replaced one at a
    time and nothing is deleted, and what each link pointed to before is
    recorded under migration-backups so the change can be undone.
    """
    from . import bridge_bundle
    releases = store.root / "bridge-releases"
    planned, problems = [], []
    # Looking takes no lock, so doctor can report while a publish is running.
    with lock(store.root / "publication.lock") if apply else contextlib.nullcontext():
        for row in store.plugins():
            if row["status"] == "removed":
                continue
            publication = Path(row["publication"])
            bundle = store.root / "bundles" / publication.name
            if not publication.is_symlink() or not bundle.is_dir() or publication.resolve() != bundle.resolve():
                problems.append({"id": row["id"], "name": row["name"],
                                 "problem": "The published link does not lead to its bundle in the library."})
                continue
            changes = []
            if os.readlink(publication) != str(bundle):
                changes.append({"link": str(publication), "from": os.readlink(publication), "to": str(bundle)})
            native = bundle / "Contents/x86_64-linux"
            current = {name: native / name for name in BRIDGE_LINKS}
            if not all(x.is_symlink() for x in current.values()):
                problems.append({"id": row["id"], "name": row["name"],
                                 "problem": "Its bridge files are not links; it was not made by this library."})
                continue
            targets = {name: Path(os.readlink(link)) for name, link in current.items()}
            if all(t.parent.parent == releases and t.exists() for t in targets.values()):
                if changes:
                    planned.append({"id": row["id"], "name": row["name"], "release": None, "links": changes})
                continue
            sources = {t.resolve().parent for t in targets.values()}
            if len(sources) != 1 or not all((native / name).exists() for name in BRIDGE_LINKS):
                problems.append({"id": row["id"], "name": row["name"],
                                 "problem": "Its bridge build is missing, so there is nothing to keep it on. "
                                            "Its links point to " + str(targets["libyabridge-vst3.so"].parent) + "."})
                continue
            source = sources.pop()
            try:
                name, _ = bridge_bundle.release_name(source)
            except (OSError, ValueError) as exc:
                problems.append({"id": row["id"], "name": row["name"],
                                 "problem": "Its bridge build at " + str(source) + " is incomplete: " + str(exc)})
                continue
            for item, target in targets.items():
                changes.append({"link": str(current[item]), "from": str(target),
                                "to": str(releases / name / item)})
            planned.append({"id": row["id"], "name": row["name"], "release": name,
                            "source": str(source), "links": changes})
        if not apply:
            return {"planned": planned, "problems": problems}
        record = store.root / "migration-backups" / "bridge-links.json"
        if record.exists():
            # A later run must not overwrite the only record of an earlier one.
            record = record.with_name("bridge-links-%d.json" % time.time_ns())
        atomic_json(record, {"schema": 1, "relinks": planned})
        done = []
        for item in planned:
            if item["release"]:
                bridge_bundle.install_release(Path(item["source"]), releases)
            for change in item["links"]:
                _repoint(Path(change["link"]), Path(change["to"]))
            done.append(item)
        atomic_json(record, {"schema": 1, "relinks": done, "applied": True})
    return {"planned": done, "problems": problems, "record": str(record)}


def adopt_current_bridge(store: Store, apply=False):
    """Move published plug-ins onto the bridge build this library now has.

    relink_publications() deliberately keeps each bundle on the exact build it
    was published against, because moving a working plug-in to different code
    is a decision, not a repair. This is that decision, made explicitly: a
    rebuilt bridge reaches existing plug-ins only through here.

    Each bundle gets the current release's chainloader and links. Class
    identities, publication paths and the DAW's own links do not change, so a
    saved project still finds its plug-ins. What every link pointed at before
    is recorded under migration-backups.
    """
    from . import bridge_bundle
    releases = store.root / "bridge-releases"
    with lock(store.root / "publication.lock") if apply else contextlib.nullcontext():
        release = store.bridge()
        planned, problems = [], []
        for row in store.plugins():
            if row["status"] == "removed":
                continue
            bundle = store.root / "bundles" / Path(row["publication"]).name
            native = bundle / "Contents/x86_64-linux"
            loader = native / (bundle.stem + ".so")
            links = {name: native / name for name in BRIDGE_LINKS}
            if not native.is_dir() or not loader.is_file() or not all(x.is_symlink() for x in links.values()):
                problems.append({"id": row["id"], "name": row["name"],
                                 "problem": "Its bridge files are not what this library publishes."})
                continue
            if all(Path(os.readlink(link)).parent == release for link in links.values()) \
                    and digest(loader) == digest(release / "libyabridge-chainloader-vst3.so"):
                continue
            changes = [{"link": str(links[name]), "from": os.readlink(links[name]),
                        "to": str(release / name)} for name in BRIDGE_LINKS]
            planned.append({"id": row["id"], "name": row["name"], "loader": str(loader), "links": changes})
        if not apply:
            return {"release": release.name, "planned": planned, "problems": problems}
        record = store.root / "migration-backups" / ("bridge-adoption-%d.json" % time.time_ns())
        atomic_json(record, {"schema": 1, "release": release.name, "moves": planned})
        done = []
        for item in planned:
            loader = Path(item["loader"])
            temporary = loader.with_name(".adopt-" + uuid.uuid4().hex)
            shutil.copy2(release / "libyabridge-chainloader-vst3.so", temporary)
            os.replace(temporary, loader)
            for change in item["links"]:
                _repoint(Path(change["link"]), Path(change["to"]))
            done.append(item)
        atomic_json(record, {"schema": 1, "release": release.name, "moves": done, "applied": True})
        return {"release": release.name, "planned": done, "problems": problems, "record": str(record)}


def scan_and_publish(store: Store, job_id):
    items = discover(store.prefix(job_id))
    failures = []
    count = 0
    for item in items:
        store.cancelled(job_id)
        store.update(job_id, "scanning", "Checking " + item["name"])
        try:
            if item["machine"] != 0x8664:
                raise HostError("32-bit plug-ins are outside this prototype's support.")
            metadata = probe(store, item["path"], job_id)
            publish(store, item, job_id, metadata)
            count += 1
        except Cancelled:
            raise
        except (HostError, ValueError) as exc:
            failures.append(item["name"] + ": " + str(exc))
    atomic_json(store.root / "jobs" / job_id / "scan-result.json", {"published": count, "failures": failures})
    if failures:
        store.update(job_id, "needs_attention", f"{count} plug-in modules published; {len(failures)} need attention. " + failures[0])
    elif not count:
        store.update(job_id, "needs_attention", "No VST3 plug-ins found yet. Finish product installation or activation, then check again.")
    else:
        store.update(job_id, "ready", f"{count} plug-in modules published. Open Bitwig to discover them.")


def work(store: Store, job_id, rescan=False):
    """Run a job, and never leave it claiming to be waiting when nothing is.

    A worker that fails before it claims the job -- losing a race for a setup
    lock is the ordinary way -- exited with the row still reading "queued".
    Nothing moved it after that, ever: no process owned it, and the interface
    showed a spinner for work that had already given up. So however this ends,
    the job stops saying it is about to happen.
    """
    try:
        return _work(store, job_id, rescan)
    except Exception as exc:
        try:
            if store.job(job_id)['status'] not in TERMINAL:
                store.update(job_id, 'cancelled' if isinstance(exc, Cancelled) else 'failed',
                             str(exc), pid=None)
        except Exception:
            pass
        try:
            # Leave the disk as it was, when the attempt got nowhere near
            # installing anything. Keeping every failure's prefix looked like
            # caution and was really a few gigabytes, invisible, for the person
            # to discover and decide about months later.
            from . import environments
            environments.tidy_after_failure(store, job_id)
        except Exception:
            pass
        raise


def _work(store: Store, job_id, rescan=False):
    job = store.job(job_id)
    if job["kind"] == "vst3":
        from .standalone import work as import_work
        return import_work(store, job_id, rescan)
    if not rescan:
        if (store.root / "jobs" / job_id / "helper-recipe.json").is_file():
            from .helper_recipes import work as helper_work
            return helper_work(store, job_id)
        from . import recipes
        if recipes.recognized(job["hash"]):
            return recipes.work(store, job_id)
    if rescan:
        config_path = store.root / "environments" / job["env_id"] / "environment.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        if (store.root / "jobs" / job_id / "helper-recipe.json").is_file() and config.get("recipe") != "managed-helper":
            raise HostError("Helper setup has not completed. Open Installation details to inspect it before continuing; Check again cannot finish or repair its installation.")
        if config.get("recipe") in ("klevgrand", "managed-helper"):
            from .vendors import work as vendor_work
            return vendor_work(store, job_id, refresh=True)
    with lock(store.root / "jobs" / job_id / "job.lock", blocking=False):
        if not rescan and job["status"] in TERMINAL:
            raise HostError("This installation has already finished. Use Check again to rescan it.")
        if rescan and not store.prefix(job_id).is_dir():
            raise HostError("This installation has no environment to check yet.")
        if rescan:
            store.update(job_id, "scanning", "Checking installed products", cancel=0)
        else:
            store.update(job_id, "preparing", "Preparing Windows support", pid=os.getpid())
        prefix = store.prefix(job_id)
        wine = None
        env = None
        try:
            store.bridge()
            check = lambda: store.cancelled(job_id)
            check()
            if rescan:
                scan_and_publish(store, job_id)
                adopt_installed_helper(store, job)
                return
            verify_installer(job)
            # Unknown installers get the same environment as everything else:
            # the selected runtime (plugg-1), this computer's machine identity
            # and the managed plug-in session. Until September 2026 they alone
            # still went to a separate plain Wine 11 build.
            from . import licensing, recipes
            report = lambda msg: store.update(job_id, "preparing", msg)
            runtime = recipes.provision(store, report, check)
            prefix.mkdir(parents=True, exist_ok=True)
            log = store.root / "jobs" / job_id / "installer.log"
            # Vendor output can contain account identifiers and authenticated
            # URLs. It is kept because this path has no other diagnostics, but
            # it is readable only by its owner and is called out in the UI.
            log.touch(mode=0o600, exist_ok=True)
            store.update(job_id, "preparing", "Creating a private Windows environment")
            full, _ = recipes.configure(store, job_id, runtime, helper_enabled=False)
            env = os.environ.copy()
            rc = run_process([full, "cmd.exe", "/c", "exit", "0"], env, log, check, 300)
            if rc != 0:
                raise HostError("Windows environment initialization failed. See installation details.")
            licensing.adopt_machine_identity(prefix.parent, [str(full)], env, check)
            session = json.loads((prefix.parent / "session.json").read_text())
            wine = Path(session["proton"]).parent / "files" / "bin" / "wineserver"
            atomic_json(prefix.parent / "environment.json", {
                "id": job_id, "recipe": "installer", "runtime": runtime_label(session),
                "session_launcher": str(prefix.parent / "launch-plugin"), "graphics_backend": "dxvk",
                "sandbox": False})
            store.update(job_id, "installing", "Complete the vendor installer in its own window")
            installer = Path(job["installer"])
            args = ([full, "msiexec", "/i", "Z:" + str(installer).replace("/", "\\")] if job["kind"] == "msi"
                    else [full, installer])
            rc = run_process(args, env, log, check, 7200, cwd=installer.parent)
            # Some installers are their vendor's manager and stay open while you
            # install products. Closing that window is how you finish, and the
            # app may report a non-zero exit for it (Kilohearts Installer exits
            # with 2). What decides success is what it installed.
            if rc != 0 and not discover(prefix):
                raise HostError(f"The vendor installer exited with code {rc} and installed no VST3 plug-ins. "
                                "See installation details.")
            # Detached launchers/helpers may still be installing. A short quiet
            # period is a heuristic, not a claim that every vendor has finished.
            store.update(job_id, "scanning", "Looking for installed VST3 plug-ins")
            last = None
            stable = 0
            for _ in range(15):
                check()
                signature = [(str(x["path"]), x["hash"]) for x in discover(prefix)]
                stable = stable + 1 if signature == last else 0
                last = signature
                if signature and stable >= 2:
                    break
                time.sleep(1)
            scan_and_publish(store, job_id)
            adopt_installed_helper(store, job)
        except Cancelled as exc:
            store.update(job_id, "cancelled", str(exc))
            if wine and wine.exists() and not any(p["env_id"] == job_id for p in store.plugins()):
                subprocess.run([wine, "-k"], env={**os.environ, "WINEPREFIX": str(prefix)}, timeout=10, capture_output=True)
        except Exception as exc:
            store.update(job_id, "failed", str(exc))
            raise
        finally:
            with store.db() as db:
                db.execute("UPDATE jobs SET pid=NULL WHERE id=?", (job_id,))


def doctor(store: Store):
    bridge = {}
    bridge_error = None
    try:
        store.bridge_source()
    except (HostError, OSError) as exc:
        bridge_error = str(exc)
    for name in ("libyabridge-vst3.so", "libyabridge-chainloader-vst3.so", "yabridge-host.exe.so", "plugg-scan"):
        path = store.bridge_directory() / name
        bridge[name] = {"present": path.is_file(), "sha256": digest(path) if path.is_file() else None}
    try:
        relink = relink_publications(store)
        outside = {"relink": len(relink["planned"]), "problems": relink["problems"]}
    except (HostError, OSError) as exc:
        outside = {"error": str(exc)}
    # A rebuilt bridge reaches published plug-ins only when they are moved onto
    # it, so say plainly when they are running older code.
    try:
        adoption = adopt_current_bridge(store)
        older = {"release": adoption["release"], "plugins_on_older_builds": len(adoption["planned"]),
                 "problems": adoption["problems"]}
    except (HostError, OSError) as exc:
        older = {"error": str(exc)}
    return {"version": "0.1.0-dev", "data": str(store.root), "publication": str(store.publication), "bridge": bridge,
            "bridge_directory": str(store.bridge_directory()), "bridge_error": bridge_error,
            # Published bundles that depend on something outside the library;
            # `relink-bundles` moves them.
            "publications_outside_library": outside,
            # Plug-ins still loading an older bridge build; `use-current-bridge` moves them.
            "bridge_in_use": older,
            "runtime": {"new_environments": json.loads((store.root / "settings.json").read_text()).get("new_environment_runtime", "UMU-Proton-10.0-4")
                        if (store.root / "settings.json").is_file() else "UMU-Proton-10.0-4",
                        "legacy_wine_provisioned": (store.root / "runtimes" / WINE["id"] / "runtime.json").exists()},
            "display": {"x11": bool(os.environ.get("DISPLAY")), "wayland": bool(os.environ.get("WAYLAND_DISPLAY"))},
            "limitations": ["Separate prefixes are not security sandboxes", "Publication validates factory discovery, not full audio or editor behavior", "Vendor-specific updates and recovery are not implemented"]}
