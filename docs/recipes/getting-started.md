# Contributing a local recipe

Recipes currently support three operations:

- graphics configuration for an existing managed environment,
- direct VST3 imports matched by exact hash, with reusable Microsoft Visual C++ runtime components,
- helper setup from an exact installer, on the shared DXVK runtime.

The complex vendor and licensing adapters stay separate. The helper section below defines what the helper path supports. Recipes cannot contain executable code. New typed operations can be added to the core when real compatibility evidence calls for them.

To add a TOML file, use **Help → Add setup recipe** or `plugg recipe add ./my-vendor.toml`. Both validate the file before saving it in `~/.config/plugg/recipes`. Plugg respects `$XDG_CONFIG_HOME`. CLI checks can also take `--recipe-dir`. Add dependency components before the recipes that use them. Plugg validates the combined catalogue, accepts an identical file added twice, and refuses different contents under an existing revision. Adding a recipe does not run it or migrate existing installations. Start with a namespaced identity, and use a new revision for each shared change:

```toml
schema = 1
id = "local.my-vendor"
revision = 1
kind = "vendor"
name = "My vendor"
requires = ["plugg.graphics-wined3d@1"]
notes = "Describe tested versions and limitations here."

[graphics.plugins]
"Program Files/Common Files/VST3/My Plugin.vst3" = "dxvk"
```

The commands, with the environment path replaced by your own managed environment:

```sh
plugg recipe validate ./my-vendor.toml
plugg recipe check --recipe-dir .
plugg recipe add ./my-vendor.toml
plugg recipe list
plugg recipe plan local.my-vendor@1 --environment /path/to/environment
plugg recipe apply local.my-vendor@1 --environment /path/to/environment
```

`validate`, `check`, `list` and `plan` do not initialize the application database or write to environments.

- `validate` checks one file.
- `check` resolves every graph in the catalogue, including local recipes. It rejects missing dependencies and conflicting settings, and needs no installed environment.
- `plan` checks the required graphics files, resolves exact dependency revisions and explains the proposed policy.
- `apply` recomputes the plan from the recipes on disk. If settings change, it requires the DAW to be idle. It records the exact resolved graph in `recipe-lock.json`. Applying an unchanged policy again does not restart a runtime. The lock is provenance. It is not a licence backup or a signed trust statement.

Components may omit a graphics default, but a complete vendor graph must supply one.

These are the supported fields:

- `schema = 1`, a namespaced `id`, a positive `revision`, `kind` (`vendor` or `component`) and a non-empty `name`.
- Optional `vendor`, `notes`, `requires` and `graphics`.
- `modules` and `vc_runtime` for direct imports.
- `bridge_patch`, `bridge_requirements` and `required_files` for existing components.
- `helper` for helper setup from an exact installer.

The sections below describe each. `graphics` has an optional `default` and a `plugins` table. At least one node in the graph must supply a default. Plug-in paths are exact paths below `drive_c`, as described in [recipe authoring](../recipe-authoring.md). There are no globs and no shell interpolation. Dependencies must be components. Missing dependencies, cycles, competing revisions, duplicate identities, unknown fields and conflicting graphics requirements all fail. The result never depends on file order. Per-plug-in settings that the graph does not mention stay as they are.

A recipe does not prove compatibility by existing. In your contribution, include exact plug-in, runtime and bridge versions, say whether each observation is manual or automated, and list known failures. Do not include installers, account URLs, credentials, licence files or copied prefixes. Shared licensing such as PACE will need explicit typed components. Plugg never infers it from a vendor name.

## Adding a direct VST3 import

Direct imports use the same catalogue as graphics recipes. `variety-of-sound.toml` defines the Variety of Sound modules, with separate VC 2013 and VC 2022 components. Another vendor can use these components without a Python adapter:

```toml
schema = 1
id = "local.example-import"
revision = 1
kind = "vendor"
name = "Example direct import"
vendor = "Example"
requires = ["plugg.graphics-dxvk@1", "plugg.vc2013-x64@1"]

# Replace this with the SHA-256 of the Windows module, not a zip or installer.
[modules."0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"]
name = "Example plug-in"
dependency = "plugg.vc2013-x64@1"
```

Run `recipe check`, then `recipe match /path/to/Example.vst3` to see the exact match and dependency before you drop the file into the app. For a bundle, the identity is the single module inside `Contents/x86_64-win`. The importer still keeps and verifies the whole bundle. A filename or vendor name alone never counts as a match. Ambiguous matches fail before any runtime is provisioned.

The typed `vc_runtime` component contains exactly `url`, `sha256` and `source`. The download URL must be HTTPS on a Microsoft download host, and the content must match its SHA-256. The importer owns the fixed installation arguments, and recipe files cannot supply commands. When you add a local recipe, you allow its matching imports to download and run this component when you add the plug-in. Review local recipes with that in mind. The host restriction and the hash limit where the file can come from. They do not prove that the package is the right one.

For now, direct imports require DXVK with no per-module overrides, one selected VC component per module, and the UMU-Proton 10.0-4 import runtime. A graph may offer several VC components, but Plugg installs only the dependency of the matched module. These limits apply to direct imports only. Helper installation is a separate operation, described below. Provisioning an unsupported component needs work in the core. Metadata that claims it works is not enough.

Before provisioning, the importer records the resolved recipe, the component and the exact module hash in the job's `recipe-lock.json`. It uses the existing dependency checks to reuse a compatible vendor environment, and prepares a fresh one otherwise. It never replays a completed job. Rescanning an existing installation does not pick up newer recipes or reinstall dependencies. The lock records intent. Job status and scan results record completion. An interrupted installation still needs inspection. Plugg does not replay it automatically.

A module with an unknown hash goes through the generic import path, with no guessed VC dependency. It does not inherit compatibility claims from a file with a similar name. `recipe plan` and `recipe apply` still mean graphics configuration of an existing environment. You run a direct import through the normal Add plug-in workflow.

## Start from a file you already have

Most of writing a recipe is copying details, such as the exact hash of a bundle, the right dependency reference and the fields this kind of recipe needs. Let the tool do that part.

~~~sh
plugg recipe init ~/Downloads/SomePlugin.vst3 \
  --vendor "Some Audio" --output my-recipe.toml
plugg recipe validate my-recipe.toml
plugg recipe explain my-recipe.toml
~~~

That leaves the parts only you can supply. One is which runtime component the plug-in needs. `plugg recipe components` lists them, each with the problem it solves. The other is what you actually saw when you tested it.

If you point `recipe init` at an installer, it generates a helper recipe instead. A helper recipe runs a Windows installer, which is a reviewed-tier capability. The generated file says so, and `recipe explain` shows it as refused at community tier. It runs from your own config directory. To share it, attach it to a compatibility report (see [CONTRIBUTING](../../CONTRIBUTING.md)).

## Check the leads first

Someone may already have done the research. `recipe leads` searches notes that other projects have published about vendors. A lead can tell you where the installer comes from and its hash, which switches install it silently, and which Wine settings it needed there.

~~~sh
plugg recipe leads valhalla
plugg recipe leads --json
~~~

The bundled leads cover 51 products from 26 vendors. Each file credits where it came from (see [third-party notes](../third-party.md)). A lead is not a recipe, and it is no evidence that anything works in Plugg. The leads were written for plain Wine, and Plugg uses a pinned UMU-Proton runtime, so treat runner names and settings as hints, and test.

Check two things in a lead before you start. If the product has a **native Linux build**, use it instead of writing a recipe. `recipe init` warns when the vendor has one. If this project **already has a recipe** for the vendor, `recipe leads` names it. Compare with it before you write another. `recipe init` also copies the vendor's leads into the generated file as comments, with the credit line.

## Inspecting a graphics application

~~~sh
plugg recipe status --environment /path/to/environment
~~~

`status` is read-only and does not load the recipe catalogue. It reports three things. It says whether the session settings still match the applied recipe record, whether the graphics operation lock is held right now, and whether a partial application needs inspection. It does not claim that a plug-in is compatible or healthy.

Graphics edits and `recipe apply` share one lock, held until the provenance records are written. They also take the helper lock, so managed helpers cannot start during the operation. A DAW launched from outside, or a manual edit, does not take part in that lock protocol. Keep the DAW idle as before.

`apply` writes its resolved intent to `recipe-application.json` before it changes any configuration. When it succeeds, it marks the record complete. If it fails and the session and launcher files are unchanged, you can retry. If it changed some files, the environment needs inspection. A process killed during apply leaves a record marked as applying. If nobody holds the operation lock any more, that needs inspection too. Plugg does not roll back, rebuild the prefix or migrate licences automatically.

To recover an interrupted graphics application, do the following by hand:

1. Keep the DAW and the helper closed.
2. Compare `session.json` and `launch-plugin` with the planned change and with the copies kept in `configuration-history`.
3. Restore or finish a consistent pair of files.
4. Check that the session manager they refer to exists.
5. Keep the old `recipe-application.json` under a diagnostic name, then plan again.

Do not delete the journal to get past a partial change you cannot explain.

For direct imports, the plug-in details in the manager show the recorded recipe revision and selected component, when a matching import record exists. They do not show the latest recipe as if it had been applied, and dependency intent alone does not prove installation. Older imports without a record still show their saved source. Sharing an iLok environment does not make another vendor's installer the source of a plug-in.

`status` also summarizes older environment records. It shows the recorded profile and runtime, whether helper and iLok launchers are configured, whether executable entry points exist, and the component hashes recorded in `dependencies.json` or `archive-components.json`. It does not read Windows registries, account databases or licence files, and it leaves out download URLs. A missing component record means "not recorded", not "nothing installed". Legacy PACE experiments in particular lack complete typed component provenance. `status` reports malformed optional records without hiding the session status.

`status` also rechecks the file and bridge requirements recorded when the recipe was applied, including hashes and the actual publication links. `requirements_match_record` is false when a required component changes or disappears, even if the session configuration still matches. It is null when no evidence was recorded. It is true when every recorded check still matches, including an explicitly empty set. `requirement_issues` explains failures. These checks are read-only. They do not prove licensing, effective DLL selection or plug-in compatibility.

## Interrupted direct imports

New direct imports record their current stage in the job's `import-state.json`. If the worker stops, the manager checks the worker's operation lock before marking the job as needing attention. It does not rely on a stale PID, kill Windows processes or restart the installation. A queued worker reads the job again after taking its lock, so it cannot repeat an import another worker has finished.

**Check again** can re-probe an import that reached the scanning stage. It will not publish a file copy that was interrupted, and it will not rerun a component installation. This matters for VST3 bundles, where the executable may have been copied before all the resources were. Earlier stages need inspection. Plugg does not clean up or recreate the prefix automatically.

## Requiring a bridge fix

A reusable component can name an exact source patch that is already built into a deployed bridge:

~~~toml
schema = 1
id = "local.editor-fix"
revision = 1
kind = "component"
name = "Required editor fix"

[bridge_patch]
sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
~~~

A vendor graph lists that component in `requires` and then limits the requirement to the exact installed module:

~~~toml
[bridge_requirements]
"Program Files/Common Files/VST3/Example.vst3" = ["local.editor-fix@1"]
~~~

Use the actual patch hash, not the example above. The built-in `plugg.plugin-alliance@2` does this with the shared `plugg.bridge-editor-detach@1` component. Revision 1 stays available with its original graphics-only meaning.

Planning uses `bridge-deployment.json` to find candidate publications and resolves their actual Windows module links. It then reads the build manifest beside each publication's actual bridge. It checks the required patch hash, that the native bridge and Windows host artifacts match, the chainloader hash and the managed marker. Requirements are per module, so unrelated plug-ins may use a different bridge. Missing installation or deployment records, or mismatched files, make planning fail. `apply` checks this evidence again while it holds its operation lock, and refuses if the deployment changed since planning.

The applied recipe records these observations. This is a local integrity and provenance check. It is not a signed trust statement, and it does not prove that a patch fixes every version of a plug-in. The operation downloads, installs and migrates no bridge. Fresh direct imports cannot provision bridge requirements yet, and reject graphs that ask for them. Runtime and PACE component requirements still need their own typed validation and provisioning.

## Requiring an existing runtime component

A component can list exact files that must exist in the selected runtime, the installed environment, or both. The built-in `plugg.ole32-foreign-window-guard@1` is a reusable requirement that does not depend on UA Connect:

~~~toml
[required_files.runtime]
"files/lib/wine/x86_64-windows/ole32.dll" = "920c6467a441ea27ccf300ec6a810407da02280d5ac3de7db312232f32858c59"

[required_files.prefix]
"windows/system32/ole32.dll" = "920c6467a441ea27ccf300ec6a810407da02280d5ac3de7db312232f32858c59"
~~~

Runtime paths are relative to the directory that contains the Proton executable named in `session.json`. Prefix paths are relative to the prefix's `drive_c`. Relative traversal fails, and so do symlinks that lead outside those roots. Plugg checks each required file by SHA-256. Two different requirements for the same path make graph composition fail.

List this component in `requires` next to the graphics component you want. Planning checks the files before it proposes any configuration, and `apply` checks them again. The applied lock records the results. Missing or mismatched files block the operation, instead of Plugg claiming a compatible setup.

These checks never patch, install or overwrite anything. They verify exact artifacts. They do not check Windows registry configuration, the effective DLL search order, licensing service health or authorization. A DLL built differently but equivalent needs its own validated component revision. Fresh direct imports reject these requirements until a matching provisioning operation exists.

A read-only check on the maintainer's system found the OLE32 component matching both the runtime DLL and the installed prefix copy, in the shared iLok environment and in the Plugin Alliance environment. That confirms the recorded artifact identity. It is not a new vendor compatibility test.

## Understanding dependency errors

Missing requirements and cycles report the path from the selected recipe to the failing dependency. Revision conflicts show both paths, for example:

```text
local.vendor@1 -> local.auth@1 -> local.runtime@1
conflicts with
local.vendor@1 -> local.helper@1 -> local.runtime@2
```

Here, two components ask for different exact revisions of the same dependency. Choose compatible, tested revisions. Changing the traversal order does not resolve the conflict. Graphics conflicts also name both recipes and the renderer each asks for. For invalid local catalogues, the manager's View problem dialog shows these details. These messages never change or repair an existing environment.

## Exact-installer helper recipes

The first helper recipe path supports fresh environments on the managed UMU-Proton 10.0-4 runtime with the default DXVK profile. Add a local TOML file like this one:

```toml
schema = 1
id = "local.example-manager"
revision = 1
kind = "vendor"
name = "Example Manager"
vendor = "Example"
requires = ["plugg.graphics-dxvk@1"]

[helper]
name = "Example Manager"
executable = "Program Files/Example/Manager.exe"
archive_tools = false
arguments = ["/quiet"]
installer_sha256 = "REPLACE_WITH_THE_INSTALLER_SHA256"
```

Replace the hash with 64 lowercase hexadecimal characters, and use only installer arguments you have tested. The executable is a literal path relative to `drive_c`. Plugg rejects Windows batch expansion and path traversal. `archive_tools = true` prepares the current pinned set of shared Windows archive tools, and saves their package identities with the job. You can also list VC runtime components in `requires`. Plugg installs the resolved components before the helper installer. This helper path does not support PACE, patched runtime or bridge requirements, or renderer overrides yet. They fail validation instead of being ignored. The existing vendor adapters stay in use, and a local helper recipe cannot quietly replace the Klevgrand adapter.

Run `recipe check --recipe-dir /path/to/recipes`. To preview the match without creating a job, run `recipe match /path/to/Setup.exe --recipe-dir /path/to/recipes`. It reports the matched recipe and the selected dependency descriptors. This checks only the EXE's identity. The companion file inventory and duplicate-environment checks happen at intake and execution. MSI helper recipes are not supported yet.

Then add the exact installer through the app or the `install` command, with its `.bin` files next to it. `recipe plan` and `recipe apply` remain the graphics operation for existing environments. They reject helper setup, module import and VC installer graphs, instead of silently skipping what those graphs would install.

At intake, Plugg records the complete selected graph and the artifact choices in the job's `helper-recipe.json`. The worker uses that snapshot, so later edits to the local TOML cannot change queued work. If the built-in runtime selection has changed, the worker refuses instead of silently picking a new runtime. Two recipes that match one installer are an error.

Setup then does the following:

1. Generates the helper launch files.
2. Verifies and runs the saved installer.
3. Checks that the expected helper exists.
4. Prepares the archive tools, if requested.
5. Runs the shared VST3 completion operation.

The resulting manager card has **Open Helper** and **Refresh library**. Closing the helper after a later launch triggers the same scan. No new vendor-specific GUI code is needed. The generic path has no vendor-specific focus fixes and never joins a shared licensing environment by itself.

The worker records each stage in `helper-setup.json`. It refuses existing prefixes and refuses to replay a finished or interrupted setup. It also blocks a second setup of the same recipe identity when that helper is already configured. Inspect interrupted jobs. Do not simply rerun an installer that may have changed licensing state. **Refresh library** is for a configured helper environment. It does not finish an installation.

For now, validation uses a synthetic installer, with simulated process and probe steps. It covers intake, pinned execution after a local recipe changes, manager card availability, the completion callback, conflicting matches, a changed runtime selection and replay refusal. It does not yet show that any further commercial vendor works through this path.

The setup journal reserves the recipe identity before a manager card exists. Another intake therefore cannot quietly create a second environment after a partial installation. Preflight errors mark the job as failed. During refresh, the app checks the journalled worker's lock before it marks a stopped monitor as needing attention. Direct imports use the same check. It never stops processes, retries installers or removes state.

Helper VC requirements use the same `vc_runtime` components as direct imports. The saved job includes their resolved asset descriptors, and the shared core operation owns the fixed Microsoft installer arguments. When a new component installs successfully, Plugg keeps the existing dependency records. A failure does not overwrite the previous record. An interrupted setup still needs inspection, because a completion record cannot tell you what the installer did.

Finishing the helper installation is separate from scanning plug-ins successfully. If the completion scan reports failures, the setup journal can be complete while the job needs attention. The helper stays available, and its card shows the scan message with the refresh action. A later helper-state result replaces an old setup warning, so a successful refresh can clear the warning on the card.

When several resolved VC component descriptions point to the same installer hash, setup runs that installer once and records each description in the provenance. This only applies within one operation. An older receipt alone does not show that the installed runtime still works, so it does not justify skipping a component operation that is newly requested.

The manager checks the helper operation lock before it shows a recorded running, opening or scanning state as busy. A reused or missing PID cannot keep a card stuck in that state. The card check creates no lock files and touches no processes. The worker still enforces exclusive access when an action runs.

**Check again** cannot finish a helper installation that stopped before its managed configuration existed. It refuses the generic scanner. Inspect the saved installation details first. Once the helper is configured, **Check again** uses the managed refresh operation and does not replay the installer. Plugg cannot repair a partial helper installation automatically.

## Browsing reusable components

In the Recipes tab, choose **Components** to browse reusable parts or **Vendor setups** to browse complete recipes. **All** shows both. Search matches component names, IDs, problem descriptions and the names of recipes that use a component. The Used by links open the exact vendor recipe revision. Each card shows the problem the component addresses, whether it configures or installs something or only checks for an existing fix, and the vendor recipes that depend on it. The component details keep the full capability report and the exact technical requirements.

Built-in components have curated evidence summaries in `plugg/recipes/component-evidence.json`. Each summary names its source notes, describes the limits of the test and is tied to the SHA-256 of the recipe file. Editing a recipe breaks that link, and Plugg does not silently carry the old evidence forward. The UI shows missing evidence as missing. These summaries are records of past tests. They do not check the current installation or claim universal compatibility.

By default, the catalogue shows the latest revision of each vendor recipe. Select **Show older recipe revisions** to browse history. This only changes the view. Existing setups and exact dependency references keep their recorded revisions.

Vendor recipe cards show their runtime policy. New installer and import recipes show the runtime that the provisioner pins. Settings-only recipes use the selected environment's runtime. Documentation-only recipes show historical runtime evidence where it exists. **What it does…** includes runtime provenance and exact download hashes. It describes the recipe, not the runtime installed in each environment right now.
