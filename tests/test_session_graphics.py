"""Ensure managed launch uses the prepared Proton graphics stack, not WineD3D."""
from pathlib import Path
import tempfile
import unittest
from plugg.proton_session import graphics_overrides

class GraphicsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.cfg={'graphics_backend':'dxvk','proton':str(root/'runtime/proton'),'prefix':str(root/'prefix')}
        self.source=root/'runtime/files/lib/wine/dxvk/x86_64-windows'
        self.target=root/'prefix/drive_c/windows/system32'
        self.source.mkdir(parents=True);self.target.mkdir(parents=True)
        for name in ('d3d11','dxgi','d3d10core','d3d9'):
            (self.source/(name+'.dll')).write_bytes(name.encode())
            (self.target/(name+'.dll')).write_bytes(name.encode())

    def test_prepared_dxvk_is_selected_explicitly(self):
        self.assertEqual(graphics_overrides(self.cfg),'d3d11=n;dxgi=n;d3d10core=n;d3d9=n')

    def test_changed_graphics_components_require_preparation(self):
        (self.target/'d3d11.dll').write_bytes(b'other runtime')
        with self.assertRaisesRegex(RuntimeError,'differ'):graphics_overrides(self.cfg)
        self.assertEqual((self.target/'d3d11.dll').read_bytes(),b'other runtime')

    def test_missing_graphics_components_do_not_silently_fall_back(self):
        (self.target/'dxgi.dll').unlink()
        with self.assertRaisesRegex(RuntimeError,'Prepare'):graphics_overrides(self.cfg)

    def test_unselected_backend_preserves_existing_fixture_behavior(self):
        self.cfg.pop('graphics_backend')
        self.assertIsNone(graphics_overrides(self.cfg))


class PolicyTests(GraphicsTests):
    def setUp(self):
        super().setUp()
        self.module='Program Files/Common Files/VST3/Example.vst3'
        self.cfg['graphics_policy']={'schema':1,'default':'wined3d','plugins':{self.module:'dxvk'}}

    def test_exact_module_and_child_isolation(self):
        from plugg.proton_session import prepare_graphics, graphics_environment
        from unittest.mock import patch
        module=Path(self.cfg['prefix'])/'drive_c'/self.module
        module.parent.mkdir(parents=True);module.write_bytes(b'plugin')
        alias=Path(self.tmp.name)/'publication.vst3';alias.symlink_to(module)
        args=['/bridge/yabridge-host.exe','VST3',str(alias),'/ipc', '123']
        prepared=prepare_graphics(self.cfg)
        with patch.dict('os.environ',{'WINEDLLOVERRIDES':'unrelated=b'}):
            import os
            self.assertIn('d3d11=n',graphics_environment(args,prepared)['WINEDLLOVERRIDES'])
            self.assertEqual(os.environ['WINEDLLOVERRIDES'],'unrelated=b')
            args[2]=str(module)+'.other'
            self.assertEqual(graphics_environment(args,prepared)['WINEDLLOVERRIDES'],graphics_overrides({'graphics_backend':'wined3d'}))
            self.assertEqual(graphics_environment(['helper.exe',str(module)],prepared)['WINEDLLOVERRIDES'],prepared['default'])

    def test_rejects_unknown_fields_backends_and_escaping_paths(self):
        from plugg.proton_session import validate_graphics_policy
        for path in ('../Example.vst3','/Example.vst3','a/../Example.vst3','C:\\Example.vst3','a//Example.vst3'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                validate_graphics_policy({'schema':1,'default':'dxvk','plugins':{path:'wined3d'}})
        for policy in ({'schema':True,'default':'dxvk','plugins':{}},
                       {'schema':1,'default':'magic','plugins':{}},
                       {'schema':1,'default':'dxvk','plugins':{},'shell':'no'},
                       {'schema':1,'default':'dxvk','plugins':{'a.vst3':'magic'}}):
            with self.assertRaises(RuntimeError):validate_graphics_policy(policy)

    def test_symlink_escape_is_rejected(self):
        from plugg.proton_session import prepare_graphics
        root=Path(self.cfg['prefix'])/'drive_c'
        (root/'escape.vst3').symlink_to(Path(self.tmp.name)/'outside.vst3')
        self.cfg['graphics_policy']['plugins']={'escape.vst3':'wined3d'}
        with self.assertRaisesRegex(RuntimeError,'escapes'):prepare_graphics(self.cfg)

    def test_mixed_policy_still_checks_dxvk_integrity(self):
        from plugg.proton_session import prepare_graphics
        (self.target/'dxgi.dll').write_bytes(b'wrong')
        with self.assertRaisesRegex(RuntimeError,'differ'):prepare_graphics(self.cfg)

    def test_group_host_cannot_silently_ignore_per_plugin_settings(self):
        from plugg.proton_session import prepare_graphics,graphics_environment
        with self.assertRaisesRegex(RuntimeError,'individual'):
            graphics_environment(['/bridge/yabridge-host.exe','group','/socket'],prepare_graphics(self.cfg))

    def test_wined3d_does_not_require_dxvk_files(self):
        from plugg.proton_session import prepare_graphics
        self.cfg['graphics_policy']={'schema':1,'default':'wined3d','plugins':{}}
        (self.target/'dxgi.dll').unlink()
        self.assertEqual(prepare_graphics(self.cfg)['default'],graphics_overrides({'graphics_backend':'wined3d'}))

    def test_apply_refuses_busy_daw_before_writing(self):
        import json
        from unittest.mock import patch
        from plugg import recipes
        directory=Path(self.tmp.name)/'environment';directory.mkdir()
        (directory/'session.json').write_text(json.dumps(self.cfg))
        (directory/'launch-plugin').write_text('original')
        with patch('plugg.ua_connect.require_idle_desktop',side_effect=RuntimeError('busy')):
            with self.assertRaisesRegex(RuntimeError,'busy'):
                recipes.configure_graphics(directory,self.cfg['graphics_policy'])
        self.assertEqual((directory/'launch-plugin').read_text(),'original')
        self.assertFalse((directory/'configuration-history').exists())

if __name__=='__main__':unittest.main()
