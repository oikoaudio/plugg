#!/bin/sh
# Compile the app's Python modules once, as root, so that no start has to and
# nobody else writes into /usr/lib/plugg. preremove.sh deletes them again.
/usr/bin/python3 -m compileall -q /usr/lib/plugg/app > /dev/null 2>&1 || true
