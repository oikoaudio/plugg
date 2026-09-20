# Reviewed recipes

Recipes here have been read by a maintainer and may declare more than a community recipe can. That is the whole difference between the two directories, and it is enforced before anyone reads a diff: `recipe explain` derives what a recipe can do from the file itself, and CI refuses one that declares more than its directory allows.

A community recipe cannot declare `run-vendor-installer` at all. A reviewed one can, which is why getting a file into this directory requires review from a code owner, and why that gate is a branch protection rule rather than a convention.

To propose one, open it against `recipes/community/` first. A maintainer decides whether to move it here, after reading what `recipe explain` says about it. It isn't something a contributor requests.

This file also keeps the directory present in a clone. Git does not track empty directories, and the catalogue check takes a missing directory as the error it usually is.
