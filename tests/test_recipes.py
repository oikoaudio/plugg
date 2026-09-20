"""Recipe recognition, dependency verification and separation from active data."""
from pathlib import Path
import tempfile
import hashlib
import json
import unittest
from unittest.mock import patch
from plugg import artifacts,core,recipes
from test_core import fake_pe
from webfixture import serve

LOOPBACK = artifacts.Source(('127.0.0.1',), ('http',), any_port=True)

class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=core.Store(self.root/'store',self.root/'published')

    def test_runtime_release_asset_host_is_allowed_but_not_arbitrary_hosts(self):
        artifacts.validate_url('https://release-assets.githubusercontent.com/example', artifacts.RUNTIME_RELEASES)
        with self.assertRaises(ValueError):
            artifacts.validate_url('https://release-assets.githubusercontent.com.example.org/example', artifacts.RUNTIME_RELEASES)

    def test_download_verification_rejects_mismatch_without_accepting_cache(self):
        with serve({'/archive':b'wrong'}) as base:
            asset={'url':base+'/archive','sha256':'0'*64}
            with self.assertRaisesRegex(core.HostError,'checksum mismatch'):
                recipes.fetch(self.store,asset,lambda _:None,lambda:None,LOOPBACK)
        self.assertEqual(list((self.store.root/'downloads').iterdir()),[])

    def test_cached_public_archive_is_verified_before_reuse(self):
        asset={'url':None,'sha256':hashlib.sha256(b'good').hexdigest()}
        with serve({'/archive':b'good'}) as base:
            asset['url']=base+'/archive'
            cached=recipes.fetch(self.store,asset,lambda _:None,lambda:None,LOOPBACK)
        # The server is gone; a verified cache entry is still reused.
        self.assertEqual(recipes.fetch(self.store,asset,lambda _:None,lambda:None,LOOPBACK),cached)

    def test_unknown_helper_version_is_not_silently_installed_with_wine(self):
        with self.assertRaisesRegex(core.HostError,'not been validated'):
            self.store.ingest(fake_pe(self.root/'Klevgrand Helper Installer.exe'))
        self.assertEqual(self.store.jobs(),[])

    def test_known_installer_routes_to_recipe_even_if_renamed(self):
        job=self.store.ingest(fake_pe(self.root/'renamed.exe'))
        with patch('plugg.recipes.recognized',return_value=True), patch('plugg.recipes.work') as work:
            core.work(self.store,job)
            work.assert_called_once_with(self.store,job)

    def test_existing_vendor_is_not_given_another_environment(self):
        with patch('plugg.recipes.recognized',return_value=True), patch('plugg.vendors.cards',return_value=[{'job':'existing','recipe':'klevgrand'}]):
            with self.assertRaisesRegex(core.HostError,'already configured'):
                self.store.ingest(fake_pe(self.root/'installer.exe'))
        self.assertEqual(self.store.jobs(),[])

    def test_other_vendor_does_not_block_klevgrand_intake(self):
        with patch('plugg.recipes.recognized',return_value=True), patch('plugg.vendors.cards',return_value=[{'job':'ni','recipe':'native-instruments-experiment'}]):
            job=self.store.ingest(fake_pe(self.root/'installer.exe'))
        self.assertEqual(self.store.job(job)['status'],'queued')

    def test_finished_recipe_cannot_be_reinstalled_or_marked_failed(self):
        job=self.store.ingest(fake_pe(self.root/'installer.exe'));self.store.update(job,'ready','Done')
        with self.assertRaisesRegex(core.HostError,'already finished'):recipes.work(self.store,job)
        self.assertEqual(self.store.job(job)['status'],'ready')


    def test_reused_runtime_rejects_modified_entry_points(self):
        assets=recipes.recipe()['runtimes']
        identity=hashlib.sha256(json.dumps(assets,sort_keys=True).encode()).hexdigest()[:16]
        target=self.store.root/'runtimes'/('proton-'+identity)
        files={}
        for name in ('UMU-Proton-10.0-4/proton','umu/umu-run','runtime/umu/steamrt3/_v2-entry-point'):
            p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'original');files[name]=core.digest(p)
        core.atomic_json(target/'runtime.json',{'assets':assets,'files':files})
        self.assertEqual(recipes.provision(self.store,lambda _:None,lambda:None),target)
        (target/'umu/umu-run').write_bytes(b'changed')
        with self.assertRaisesRegex(core.HostError,'entry point changed'):
            recipes.provision(self.store,lambda _:None,lambda:None)

    def test_unrecognized_installer_cannot_use_unattended_recipe_arguments(self):
        job=self.store.ingest(fake_pe(self.root/'unrecognized.exe'))
        with patch('plugg.recipes.provision') as provision:
            with self.assertRaisesRegex(core.HostError,'not been validated'):recipes.work(self.store,job)
            provision.assert_not_called()

if __name__=='__main__':unittest.main()
