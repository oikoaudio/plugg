# What CI checks

`checks.yml` runs four jobs on every pull request and every push to `main`. While the repository is private they are skipped, since private repositories pay for Actions minutes.

- **Tests.** The unit suite and the recipe catalogue check, on Python 3.12 and 3.13. No Wine, no vendor accounts, no network.
- **Recipe review.** Posts a report on every changed recipe into the job summary, and fails if a recipe declares more than its directory allows. See [recipe trust](../../docs/recipe-trust.md).
- **Interface smoke test.** Builds the GTK window under Xvfb and exercises its controls.
- **Guardrail audit.** Runs the tests behind the security rules. Every operation that writes into a prefix passes the licensing guard, download sources stay HTTPS-only and on their allowlist, and the recipe capability ceilings hold.

None of this proves a plug-in works. That evidence comes from a human running the checks in CONTRIBUTING against a real environment.
