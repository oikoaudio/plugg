#!/bin/sh
# Plugg, as installed by a distribution package (.deb, .rpm, the generic
# tarball and the Arch package). The app is in /usr/lib/plugg/app and runs on
# the system Python, with the distribution's PyGObject and GTK 4. It is put on
# the module path inside Python, not through PYTHONPATH, so the path does not
# leak into Proton or vendor programs (the same way plugg.core.plugg_command
# starts Plugg). -P keeps the current directory off the path. Nothing here
# names a Python version, so a new one on the system does not strand the app.
exec /usr/bin/python3 -P -c 'import runpy, sys; sys.path.insert(0, "/usr/lib/plugg/app"); runpy.run_module("plugg", run_name="__main__", alter_sys=True)' "$@"
