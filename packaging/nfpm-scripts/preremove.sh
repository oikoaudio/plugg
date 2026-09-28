#!/bin/sh
# Delete the compiled modules postinstall.sh wrote, which the package does not
# own, so that removing it leaves no /usr/lib/plugg behind. rpm passes 0 on
# removal and 1 on upgrade; dpkg passes remove or upgrade. An upgrade keeps
# them, and the new version's postinstall.sh brings them up to date.
case "$1" in
    0|remove)
        /usr/bin/python3 -c 'import pathlib, shutil
for path in list(pathlib.Path("/usr/lib/plugg/app").rglob("__pycache__")):
    shutil.rmtree(path)' || true
        ;;
esac
