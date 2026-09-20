import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from plugg import recipe_engine as engine,recipe_report,helper_recipes,native_access,core,powershell_component,artifacts

class NativeAccessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.records=engine.catalogue([Path(engine.__file__).parent/'recipes/community'])
 def test_exact_installer_resolves_powershell_and_profile(self):
  fingerprint=self.records['plugg.native-instruments@1']['data']['helper']['installer_sha256']
  selected=helper_recipes.catalogue(self.records)[fingerprint]
  self.assertEqual(selected['helper_profile'],'native-access')
  self.assertEqual(selected['powershell_asset'],powershell_component.ASSET)
  report=recipe_report.report(self.records,'plugg.native-instruments@1')
  self.assertIn('install-powershell',report['capabilities'])
  self.assertTrue(any(item['url']==powershell_component.ASSET['url'] for item in report['downloads']))
 def test_component_cannot_be_applied_as_graphics(self):
  with self.assertRaisesRegex(ValueError,'helper recipes'):
   engine.plan(self.records,'plugg.native-instruments@1',self.root/'absent')
  self.assertFalse((self.root/'absent').exists())
 def test_unknown_app_blocks_runtime_stop(self):
  with patch.object(native_access.vendors,'running_programs',return_value=[(12,'yabridge-host.exe')]),patch.object(native_access.subprocess,'run') as run:
   with self.assertRaisesRegex(core.HostError,'Close applications'):
    native_access.prepare_runtime(self.root)
   run.assert_not_called()
 def test_configure_creates_private_download_dir_and_callback_only(self):
  (self.root/'prefix/drive_c').mkdir(parents=True)
  with patch.object(native_access.licensing,'guard'),patch.object(native_access.subprocess,'run') as run:
   native_access.configure(self.root)
   run.assert_not_called()
  self.assertTrue((self.root/'prefix/drive_c/Native Instruments Downloads').is_dir())
  self.assertEqual(json.loads((self.root/'native-access-protocol.json').read_text())['application'],str(self.root/'prefix/drive_c'/native_access.APPLICATION))
 def test_powershell_source_is_limited_to_microsoft_project(self):
  artifacts.validate_entry_url(powershell_component.ASSET['url'],powershell_component.SOURCE)
  with self.assertRaises(ValueError):
   artifacts.validate_entry_url('https://github.com/other/PowerShell/releases/download/v1/a.msi',powershell_component.SOURCE)

 def test_current_revision_installs_ntk_and_keeps_history(self):
  fingerprint=self.records['plugg.native-instruments@2']['data']['helper']['installer_sha256']
  selected=helper_recipes.catalogue(self.records)[fingerprint]
  self.assertEqual(selected['reference'],'plugg.native-instruments@2')
  self.assertIn('ntk_daemon',selected)
  self.assertIn('plugg.native-instruments@1',self.records)
  self.assertIn('install-ntk-daemon',recipe_report.report(self.records,selected['reference'])['capabilities'])
 def test_ntk_rejects_wrong_installer_before_execution(self):
  from plugg import ntk_component
  p=self.root/'prefix/drive_c'/ntk_component.SPEC['installer']
  p.parent.mkdir(parents=True);p.write_bytes(b'wrong installer')
  with patch.object(ntk_component.licensing,'guard'),patch.object(ntk_component,'require_available'),patch.object(ntk_component.subprocess,'Popen') as launch:
   with self.assertRaisesRegex(core.HostError,'reviewed version'):
    ntk_component.install(self.root,'launcher',lambda _:None,lambda:None)
   launch.assert_not_called()
 def test_ntk_record_cannot_escape_prefix(self):
  from plugg import ntk_component
  p=self.root/'prefix/drive_c';p.mkdir(parents=True)
  outside=self.root/'outside';outside.mkdir()
  (p/'users').symlink_to(outside,target_is_directory=True)
  with self.assertRaisesRegex(core.HostError,'escapes'):
   ntk_component.installed(self.root)
