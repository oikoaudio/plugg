#!/usr/bin/env python3
"""Compatibility entry point for the isolated runtime tests.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import runpy,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
runpy.run_module("plugg.proton_session",run_name="__main__")
