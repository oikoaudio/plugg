#!/usr/bin/env python3
"""Real installer + bridge/audio integration test; never publishes to the user library."""
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import concurrent.futures
import json
import os
import subprocess
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plugg import core


def main():
    root = ROOT / ".test-integration" / uuid.uuid4().hex
    root.mkdir(parents=True)
    store = core.Store(root / "library", root / "published")
    # Reuse the download cache, with independent prefixes for every test run.
    cache = core.Store(ROOT / ".test-data")
    wine = core.provision_wine(cache, lambda message: print(message, flush=True))
    fixture = ROOT / "build/fixtures/Install-Test-Gain.exe"
    if not fixture.is_file():
        raise RuntimeError("Build the test installer with scripts/build-fixture.sh first")
    job = store.ingest(fixture)
    prefix = store.prefix(job)
    try:
        with patch("plugg.core.provision_wine", return_value=wine):
            core.work(store, job)
        assert store.job(job)["status"] == "ready", store.job(job)
        plugin, = store.plugins()
        target = Path(plugin["publication"])
        assert target.is_symlink()
        native = target / "Contents/x86_64-linux" / (target.stem + ".so")
        def audio(instance):
            output = root / f"audio-{instance}.json"
            env = os.environ.copy()
            env.update(WINEPREFIX="/wrong-prefix", WINELOADER="/wrong-loader", WINEDEBUG="-all")
            rc = core.run_process([store.bridge()/"plugg-scan", native, output, "--audio"], env,
                                  root/f"audio-{instance}.log", timeout=30)
            assert rc == 0, (instance, rc)
            data = json.loads(output.read_text())
            assert data["audio_fixture_passed"]
            return data
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            audio_results = list(pool.map(audio, range(2)))
        # Rescan must neither rerun the installer nor duplicate publication.
        with patch("plugg.core.provision_wine", side_effect=AssertionError("rescan reprovisioned")):
            core.work(store, job, rescan=True)
        assert len(store.plugins()) == 1 and len(list(store.publication.iterdir())) == 1
        results = {"passed": True, "job": job, "installer_sha256": core.digest(fixture),
                   "runtime": core.WINE, "bridge": json.loads((store.bridge()/"build.json").read_text()),
                   "audio_instances": audio_results, "blocks_per_instance": 1000,
                   "block_size": 128, "sample_rate": 48000, "rescan_idempotent": True,
                   "bitwig_tested": False, "vendor_plugins_tested": False}
        core.atomic_json(root/"results.json", results)
        print("Integration passed:", root/"results.json")
    finally:
        # Only this newly created test prefix; no user Wine services are touched.
        if prefix.exists():
            subprocess.run([wine.parent/"wineserver", "-k"], env=core.runtime_env(prefix,wine),
                           capture_output=True, timeout=10)


if __name__ == "__main__":
    main()
