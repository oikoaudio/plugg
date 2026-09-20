"""The patched runtime is a new directory: the base and every existing environment stay as they are."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugg import core, licensing, recipes, runtime_overlay as overlay

REPO = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RuntimeOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'library/runtimes/base/UMU-Proton-10.0-4'
        wine = self.base / 'files/lib/wine'
        for arch in ('x86_64-windows', 'i386-windows'):
            (wine / arch).mkdir(parents=True)
            (wine / arch / 'rundll32.exe').write_bytes(b'stock ' + arch.encode())
            (wine / arch / 'kernel32.dll').write_bytes(b'kernel ' + arch.encode())
        (self.base / 'proton').write_bytes(b'#!/usr/bin/env python3\n')
        (self.base / 'files/share').mkdir()
        (self.base / 'files/share/link').symlink_to('../lib')
        self.artifacts = self.root / 'artifacts'
        files = {}
        for arch in ('x86_64-windows', 'i386-windows'):
            (self.artifacts / arch).mkdir(parents=True)
            data = b'patched ' + arch.encode()
            (self.artifacts / arch / 'rundll32.exe').write_bytes(data)
            files[arch + '/rundll32.exe'] = {'sha256': sha(data), 'patch': 'patches/wine/0001-x.patch'}
        self.spec = {'name': 'test-1', 'purpose': 'test', 'files': files,
                     'base': {'release': 'UMU-Proton-10.0-4', 'proton_sha256': sha(b'#!/usr/bin/env python3\n')}}
        self.runtimes = self.root / 'library/runtimes'

    def snapshot(self):
        return {str(path.relative_to(self.base)): (path.read_bytes() if path.is_file() and not path.is_symlink() else None)
                for path in sorted(self.base.rglob('*'))}

    def test_assembly_creates_a_new_runtime_and_leaves_the_base_alone(self):
        before = self.snapshot()
        target = overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(target.name, overlay.directory_name(self.spec))
        self.assertEqual((target / 'files/lib/wine/i386-windows/rundll32.exe').read_bytes(), b'patched i386-windows')
        self.assertEqual((target / 'files/lib/wine/i386-windows/kernel32.dll').read_bytes(), b'kernel i386-windows')
        self.assertTrue((target / 'files/share/link').is_symlink())
        record = json.loads((target / overlay.MANIFEST).read_text())
        self.assertEqual(record['files']['files/lib/wine/x86_64-windows/rundll32.exe']['base_sha256'],
                         sha(b'stock x86_64-windows'))

    def test_repeating_is_a_no_op(self):
        first = overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)
        self.assertEqual(overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes), first)

    def test_a_module_with_the_wrong_hash_is_refused(self):
        (self.artifacts / 'i386-windows/rundll32.exe').write_bytes(b'something else')
        with self.assertRaisesRegex(core.HostError, 'different SHA-256'):
            overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)
        self.assertEqual([path.name for path in self.runtimes.iterdir()], ['base'])

    def test_a_different_proton_build_is_refused(self):
        (self.base / 'proton').write_bytes(b'another build')
        with self.assertRaisesRegex(core.HostError, 'not the UMU-Proton-10.0-4 build'):
            overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)

    def test_verification_notices_a_changed_module(self):
        target = overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)
        path = target / 'files/lib/wine/x86_64-windows/rundll32.exe'
        path.unlink()
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(core.HostError, 'changed since assembly'):
            overlay.verify(self.spec, target)

    def test_new_environments_use_the_selected_runtime_only_after_selection(self):
        library = self.root / 'library'
        core.atomic_json(library / 'settings.json', {'publication': '/tmp/x', 'schema': 1})
        overlay.assemble(self.spec, self.base, self.artifacts, self.runtimes)
        with patch.object(overlay, 'overlays', return_value={'test-1': self.spec}):
            self.assertEqual(overlay.proton_for_new_environment(library, self.base), self.base)
            overlay.select_for_new_environments(library, 'test-1')
            self.assertEqual(overlay.proton_for_new_environment(library, self.base).name,
                             overlay.directory_name(self.spec))
            self.assertEqual(json.loads((library / 'settings.json').read_text())['publication'], '/tmp/x')
            overlay.select_for_new_environments(library, None)
            self.assertEqual(overlay.proton_for_new_environment(library, self.base), self.base)

    def test_selecting_a_runtime_that_was_never_assembled_fails(self):
        library = self.root / 'library'
        with patch.object(overlay, 'overlays', return_value={'test-1': self.spec}):
            with self.assertRaisesRegex(core.HostError, 'no build record'):
                overlay.select_for_new_environments(library, 'test-1')

    def test_inventory_names_the_environments_on_each_runtime(self):
        library = self.root / 'library'
        environment = library / 'environments/abc'
        environment.mkdir(parents=True)
        (environment / 'session.json').write_text(json.dumps({'proton': str(self.base / 'proton')}))
        listing = overlay.inventory(library)
        self.assertEqual(listing['runtimes'], [{'directory': 'base', 'overlay': None, 'environments': ['abc']}])


class ConfigureTests(unittest.TestCase):
    def test_an_existing_environment_changing_runtime_goes_through_the_licensing_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = type('S', (), {'root': root, 'prefix': lambda self, job: root / 'environments' / job / 'prefix'})()
            directory = root / 'environments/job'
            (directory / 'prefix').mkdir(parents=True)
            (directory / 'session.json').write_text(json.dumps({'proton': '/elsewhere/proton'}))
            runtime = root / 'runtime'
            (runtime / 'UMU-Proton-10.0-4').mkdir(parents=True)
            refusal = licensing.LicensedEnvironmentError('refused')
            with patch.object(licensing, 'guard', side_effect=refusal) as guard:
                with self.assertRaises(licensing.LicensedEnvironmentError):
                    recipes.configure(store, 'job', runtime, helper_enabled=False)
            guard.assert_called_once_with(directory, 'replace_runtime')


class ShippedDescriptionTests(unittest.TestCase):
    def test_the_shipped_runtime_matches_the_recorded_builds(self):
        spec = overlay.overlay('plugg-1')
        series = json.loads((REPO / 'patches/wine/series.json').read_text())
        provenance = json.loads((REPO / 'patches/0004-ole32-revoke-foreign-drop-target.provenance.json').read_text())
        self.assertEqual(spec['base']['wine_revision'], series['wine_revision'])
        self.assertEqual(spec['base']['wine_revision'], provenance['wine_revision'])
        for relative, digest in series['artifacts_sha256'].items():
            self.assertEqual(spec['files'][relative]['sha256'], digest)
        self.assertEqual(spec['files']['x86_64-windows/ole32.dll']['sha256'], provenance['ole32-guard.dll_sha256'])
        for entry in spec['files'].values():
            self.assertTrue((REPO / entry['patch']).is_file(), entry['patch'])

    def test_the_installed_runtime_keeps_its_directory_name(self):
        # Environments record this path; the iLok environment was activated on it.
        self.assertEqual(overlay.directory_name(overlay.overlay('plugg-1')), 'proton-10.0-4-plugg-1-440a6d29c2e6')

    def test_notes_and_build_instructions_do_not_rename_a_runtime(self):
        spec = dict(overlay.overlay('plugg-1'), purpose='reworded', validated=['more'], build={})
        spec.pop('identity')
        spec.pop('content_sha256')
        reworded = dict(spec, not_yet_tested=[])
        self.assertEqual(overlay.identity(spec), overlay.identity(reworded))

    def test_changing_a_named_runtime_is_refused(self):
        data = json.loads(overlay.SPEC.read_text())
        data['overlays'][0]['files']['x86_64-windows/rundll32.exe']['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / 'runtime-overlays.json'
            changed.write_text(json.dumps(data))
            with patch.object(overlay, 'SPEC', changed):
                with self.assertRaisesRegex(core.HostError, 'new runtime'):
                    overlay.overlays()

    def test_the_build_description_covers_every_module(self):
        spec = overlay.overlay('plugg-1')
        built = [relative for tree in spec['build']['trees'] for relative in tree['files']]
        self.assertEqual(sorted(built), sorted(spec['files']))
        for tree in spec['build']['trees']:
            for entry in tree['patches']:
                self.assertEqual(sha((REPO / entry['patch']).read_bytes()), entry['sha256'], entry['patch'])
        applied = {entry['patch'] for tree in spec['build']['trees'] for entry in tree['patches']}
        self.assertEqual(applied, {entry['patch'] for entry in spec['files'].values()})

    def test_published_modules_come_only_from_this_projects_releases(self):
        from plugg import artifacts
        release = overlay.overlay('plugg-1')['release']
        self.assertRegex(release['sha256'], '^[0-9a-f]{64}$')
        self.assertTrue(release['url'].startswith('https://github.com/oikoaudio/plugg/releases/download/'))
        artifacts.validate_entry_url(release['url'], artifacts.RUNTIME_RELEASES)
        with self.assertRaises(ValueError):
            artifacts.validate_entry_url('https://github.com/someone/plugg/releases/download/x/a.tar',
                                         artifacts.RUNTIME_RELEASES)

    def test_downloaded_modules_are_unpacked_for_assembly(self):
        import tarfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'modules.tar'
            with tarfile.open(archive, 'w') as tar:
                for arch in ('x86_64-windows', 'i386-windows'):
                    data = b'patched ' + arch.encode()
                    info = tarfile.TarInfo(arch + '/rundll32.exe')
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            store = type('S', (), {'root': root})()
            spec = {'name': 'test-1', 'release': {'url': 'https://example.invalid/m.tar', 'sha256': '0' * 64}}
            with patch('plugg.artifacts.fetch', return_value=archive) as fetch:
                modules = overlay.download_modules(store, spec, root / 'modules', report=lambda _: None)
            self.assertEqual(fetch.call_args.args[4], __import__('plugg.artifacts').artifacts.RUNTIME_RELEASES)
            self.assertEqual((modules / 'i386-windows/rundll32.exe').read_bytes(), b'patched i386-windows')

    def test_a_runtime_without_published_modules_says_how_to_build_them(self):
        with self.assertRaisesRegex(core.HostError, 'build-runtime-overlay'):
            overlay.download_modules(None, {'name': 'x'}, '/nonexistent')

    def test_the_runtime_command_lists_without_changing_anything(self):
        from plugg.__main__ import main
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with patch('sys.argv', ['plugg', '--data', temporary, 'runtime', 'plan']), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            self.assertFalse(json.loads(output.getvalue())['changes_existing_files'])


if __name__ == '__main__':
    unittest.main()
