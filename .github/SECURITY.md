# Security

This is a developer preview that runs Windows software on Linux and manages environments holding people's licences. Treat it accordingly.

## Reporting

Report privately through GitHub's security advisories rather than a public issue. If that is not available to you, say that you have a security report in an issue without details, and wait to be contacted.

Please include what an attacker would need (a shared recipe, a crafted plug-in file, network position, local access), what they gain, and the smallest reproduction. A demonstrated finding is worth far more than a described one.

There is no bounty and no guaranteed response time. This is one person's side project, but security reports come first.

## What is in scope

- A shared recipe causing anything outside its declared capabilities: running code on the Linux host, writing outside its environment, reaching a host the allowlist does not name, or bypassing a hash pin.
- Any path that changes or destroys an environment holding activations without the licensing guard refusing first.
- Leaking credentials, licence material, account data or machine identifiers into a log, a record, or anything the project suggests sharing.
- Escaping the recipe capability ceilings enforced in `plugg/recipe_report.py`.

## What is not

- **A Windows prefix is not a security sandbox.** It is an environment, not a boundary. A malicious Windows plug-in running inside one can reach the user's files, exactly as it could on Windows. This is documented, not a defect.
- Wine, Proton, yabridge and vendor software have their own security contacts. Report issues in them upstream; tell us if the project's use makes it worse.
- Denial of service through a recipe the user installed deliberately, beyond the bounds already enforced.

## What the project does not do

It does not inspect, alter, emulate or bypass any licensing check, and it will not accept a contribution that does. Recipes cannot carry commands, and that is enforced by the schema rather than by review.
