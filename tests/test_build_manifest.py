import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bridge_manifest', Path(__file__).resolve().parents[1] / 'scripts/bridge-manifest.py')
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


class BuildManifestTest(unittest.TestCase):
    def test_observed_dependencies_and_only_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build, output = root / 'build', root / 'output'
            info = build / 'meson-info'
            info.mkdir(parents=True)
            output.mkdir()
            for name in manifest.ARTIFACTS:
                (output / name).write_bytes(name.encode())
            (output / 'unrelated-private-file').write_text('not an artifact')
            for name in ('native/scan.cpp', 'native/scan_formats.cpp', 'scripts/build-bridge.sh', 'scripts/bridge-manifest.py', 'vendor/yabridge/cross-wine.conf', 'vendor/yabridge/subprojects/example.wrap', 'patches/0001.patch'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('fixture')
            (root / 'patches/yabridge-series.json').write_text(json.dumps(['0001.patch']))
            (root / 'patches/wine-only.patch').write_text('not a yabridge patch')
            data = {
                'compilers': {'build': {'cpp': {'id': 'gcc', 'version': 'test', 'exelist': ['/private/path/c++']}}},
                'dependencies': [{'name': 'asio', 'type': 'pkgconfig', 'version': 'system-version', 'compile_args': ['/private/path']}],
                'projectinfo': {'subprojects': [{'name': 'asio', 'version': 'declared-version'}]},
                'buildoptions': [{'name': 'force_fallback_for', 'value': ['asio']}, {'name': 'wrap_mode', 'value': 'default'}, {'name': 'prefix', 'value': '/private/path'},
                                 {'name': 'cpp_args', 'machine': 'host', 'value': ['-march=native']}, {'name': 'cpp_link_args', 'machine': 'build', 'value': []}],
            }
            subproject = root / 'vendor/yabridge/subprojects/asio'
            (subproject / '.git').mkdir(parents=True)
            (subproject / 'meson.build').write_text('overlay fixture')
            for name, value in data.items():
                (info / ('intro-' + name + '.json')).write_text(json.dumps(value))
            with patch.object(manifest.subprocess, 'check_output', return_value='fixture-version\n'):
                result = manifest.manifest(root, build, output)
            self.assertEqual(set(result['patches']), {'patches/0001.patch'})
            self.assertEqual(set(result['files']), set(manifest.ARTIFACTS))
            self.assertEqual(result['build_inputs']['dependencies'][0]['version'], 'system-version')
            self.assertEqual(result['build_inputs']['subprojects'][0]['git_revision'], 'fixture-version')
            self.assertEqual(result['build_inputs']['subprojects'][0]['meson_version'], 'declared-version')
            self.assertEqual(result['build_inputs']['options']['force_fallback_for'], ['asio'])
            self.assertEqual(result['build_inputs']['arguments'], {'host.cpp_args': ['-march=native'], 'build.cpp_link_args': []})
            self.assertNotIn('/private/path', json.dumps(result))
            (output / 'plugg-scan').unlink()
            with patch.object(manifest.subprocess, 'check_output', return_value='fixture-version\n'):
                with self.assertRaises(FileNotFoundError):
                    manifest.manifest(root, build, output)
