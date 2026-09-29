# User-authored recipes

This page describes where recipes are heading. [The recipe guide](recipes/getting-started.md) has the supported TOML schema, commands and examples to copy. Direct imports, graphics, requirements on existing components and a helper path for exact installers are implemented. The wider installer and licensing contract below is still a proposal. Do not use its conceptual fields as recipe syntax.

## Design goal

A user should be able to copy a small example, describe what a particular installer or plug-in version needs, validate it, and add it locally without changing the application. The documentation alone should be enough for a person or a coding agent to do this. Recipes describe requirements and supported operations in a portable way. They are not a general system for executable plug-ins.

Keep the ordinary case short. The defaults cover a user-supplied installer, interactive installation, the standard installed VST3 locations and automatic discovery afterwards. Ask for extra fields only when a product needs something different.

## Three extension levels

1. **Recipe data.** Product identity, applicable versions, required components, installer selection, helper path, discovery roots and supported launch options. Most new vendors should fit here without any change to application code.
2. **Reusable component description.** A versioned VC runtime, archive utility, graphics configuration or patched runtime artifact, detected and installed through existing operations. Several vendor recipes can require the same component. PACE belongs here, separate from UA Connect.
3. **New core operation.** When the existing vocabulary cannot express a real compatibility requirement, add a small, tested operation to the core and document its interface. A local developer can extend the source. Recipe files never import arbitrary Python or run embedded shell scripts.

Contributors have a defined path when a recipe is not enough, and files that claim to be declarative contain no custom code. Keep manual steps possible and visible. Mark a setup as waiting for a manual step instead of pretending it is automated.

## Minimal public interface

Use one human-readable format, with a published schema and field reference. TOML is the first candidate. Do not maintain competing JSON, YAML and TOML authoring formats. The loader must reject unsupported schema versions and unknown operational fields with precise errors.

Document these concepts:

| Concept | Meaning |
| --- | --- |
| Schema version | Which recipe interface the app understands |
| Recipe ID and revision | Stable identity and an immutable revision of this description |
| Applies to | Vendor or product, architecture, and known installer and product versions |
| Inputs | User-supplied installation sets or permitted component artifacts |
| Requirements | Named components and compatible versions or capabilities |
| Environment policy | A separate environment, or an explicit compatible licensing group |
| Operations | Supported install, configure, launch and discovery actions |
| Detection and validation | Evidence that a dependency exists and that the result works |
| Evidence and limitations | Tested versions, hosts, desktop behaviour and known failures |

Keep the recipe revision, installer version, installed product version and runtime version apart. A newer recipe does not give permission to update an existing environment. Resolve requirements to exact artifact identities and hashes in an installation lock record, and record the selected recipe revision and content hash there too.

Start with exact tested component versions and a small set of supported alternatives. Do not build a general package solver. If requirements conflict, explain the conflict and stop planning that combination. A capability such as a required Wine fix must map to a verified build. A label alone does not prove that the fix is present.

## Dependencies introduced by an authorization system

Requirements can be transitive. A product recipe can declare that it needs an authorization system such as iLok/PACE. The selected licensing component then declares its own required services, runtime capabilities and configuration. Vendor recipes should not each repeat those prerequisites.

For example, a tested product recipe may require iLok/PACE machine authorization. The selected PACE component may in turn require a particular compatible Wine build and service configuration. These are three separate records. One is the product's licensing requirement, one is the implementation of that requirement, and one is the exact set of artifacts selected for this installation. Do not assume that every iLok product accepts the same PACE version or activation method. Record the supported versions, and whether machine, cloud or USB authorization has actually been tested.

Licensing requirements also bring constraints on state and environment. Plug-ins and helpers that need the same local PACE service must use a compatible environment. Prefer joining the user's existing compatible iLok environment, and keep its identity and activations. Installing a component must never quietly create another licensed machine, move an activation or change an existing environment's runtime.

Keep the implementation small. Expand named requirements recursively, detect cycles, merge identical requirements and report incompatible versions or runtime constraints. Show the reason chain in the preview, for example "this product needs iLok/PACE, which needs this tested runtime capability". If no supported combination fits the existing environment, report the conflict and the available choices. Never create a new prefix silently. A helper's bundled PACE installer is a proposed dependency update. It has no authority to replace the shared installation.

The vendor stays the product's display identity. An iLok tag and a shared licensing-management action show the relationship without grouping Soundtoys, oeksound and Universal Audio as one vendor. Reuse this pattern for other authorization systems when real compatibility evidence calls for it. Do not build a universal licensing framework in advance.

## Local addition and sharing

Provide a user recipe directory, separate from the bundled recipes, and an explicit Add recipe action. Use a namespaced identity such as `local.example.product`, so a local addition cannot silently replace a bundled recipe. Allow the user to pick a local variant deliberately, and keep its provenance. Updating or removing a recipe file must never change or remove an existing installation. Keep the resolved recipe with its installation record.

Adding a recipe validates its metadata only. The preview resolves inputs, dependencies, the target environment and the proposed changes without launching installers. Applying the reviewed plan uses the same core operations as bundled recipes. This describes how it works inside. It does not mean an extra confirmation dialog for every routine installation.

State the trust boundary plainly. Schema validation catches mistakes, not malicious installer behaviour. Recipes are setup instructions, not authority to override the user's choices. Component downloads need permitted sources and integrity checks. User-supplied commercial installers and the files next to them stay local. Limit path expansion and writes to declared managed locations, and reject path traversal and symlinks that lead elsewhere. Where a product needs an external content path, keep it through explicit configuration managed by the app.

No automatic remote recipe subscription or marketplace is needed. Start with local folders and text files people can share. Keep credentials, licences, authenticated URLs and machine-specific paths out of shared recipes.

## Patched runtime components

A difficult recipe may need a particular patched runtime build. The component record names its upstream revision, patch set, artifact hashes, architecture, licence and source obligations, and regression evidence. The recipe refers to that component. It does not repeat patch commands or modify a shared runtime in place.

Build patched artifacts separately, and keep the previous runtime while anything refers to it. Treat replacing the runtime of an existing environment as a migration with compatibility checks, especially where licensing identity is involved. Do not assume a patched DLL can be mixed into any Wine build. Declare the compatible base build and deploy the whole matching set of artifacts. Packaging third-party binaries must respect their redistribution terms. A local experiment is not automatically a redistributable dependency.

The current PACE workarounds are experimental evidence for this design. They are not a verified public PACE component, and the private MSI modification must never become a hidden default.

## Author workflow and acceptance

Document one example to copy and edit for a direct VST3 import, and another for a helper-based installer. Include the complete field reference, the inputs and results of each operation, example errors, the version policy and a short troubleshooting guide. An agent should need only these docs and the schema, not knowledge passed on from earlier conversations.

The author workflow has these steps:

1. Copy an example.
2. Identify the inputs and requirements.
3. Validate.
4. Preview.
5. Test in a disposable environment with no activations.
6. Record the evidence.
7. Add the recipe locally, or submit it for review.

Checks that depend on activation happen separately, in a persistent environment chosen on purpose.

The first implementation is complete when someone can add a second recipe using only a recipe file and existing components, without changing the GUI or vendor-specific Python dispatch. Test invalid fields, unresolved and conflicting dependencies, input mismatches and repeated application. Add a new core operation only when a concrete recipe shows the need.

## Reusing installer completion (implemented Python interface)

A helper adapter calls `plugg.vendors.finish_installation(store, job_id, *, busy=None, before_scan=None, after_scan=None)` once its installer has finished and its environment is free for discovery. This is the current internal interface. The public TOML schema has no declarative helper-installer operation for it.

The caller holds the environment's `helper.lock` and the owning job's `job.lock` until completion. The shared workflow waits for the VST3 content to stay unchanged for five seconds, for up to ten minutes. It then probes and publishes new modules, keeps unchanged publications, and records results in `vendor-scan-result.json` and `helper-state.json`. A failed probe does not stop the other modules from being considered. Plugg reports changed installed versions instead of silently updating them. It scans only installed plug-in locations: VST3, and VST2 and CLAP when the library publishes them. Installer caches and AAX are never publication sources.

The optional hooks each do one narrow job:

- `busy(prefix) -> bool` reports whether installation or runtime activity blocks scanning. The default checks for Windows applications. A helper that uses the full runtime can require every prefix process to finish.
- `before_scan()` checks that the runtime is ready before probing. Raise an exception to stop.
- `after_scan()` releases scan resources the adapter owns. It runs in `finally` once scanning has started, including after a failure. It must leave active user sessions and the licensing identity alone.

Klevgrand and UA Connect use this interface today. UA supplies its check that the DAW is idle and its cleanup of the guarded runtime. Future vendor adapters can reuse discovery without copying UA's Electron flags, Hyprland window handling or PACE dependencies.

## Implemented graphics policy fragment

The wider recipe contract above is still a proposal. This small JSON fragment is implemented now, in the project's existing JSON recipe files. That does not commit the future full recipe schema to JSON.

`plugg/recipes/plugin-alliance-graphics.json` is the current Plugin Alliance example:

```json
{
  "schema": 1,
  "default": "wined3d",
  "plugins": {
    "Program Files/Common Files/VST3/Black Box Analog Design HG-2.vst3": "wined3d",
    "Program Files/Common Files/VST3/ADPTR MetricAB.vst3": "dxvk",
    "Program Files/Common Files/VST3/Pro Audio DSP DSM V3.vst3": "dxvk"
  }
}
```

The paths identify Windows VST3 modules relative to the environment's `drive_c`. They are exact, case-sensitive Linux paths, not display names, class IDs, globs or generated publication IDs. Publication symlinks resolve to the installed module. Unknown modules and helper processes get the default. All classes in one module share one renderer. Plugg rejects grouped yabridge hosts when per-plug-in settings exist, because one process cannot have several DLL-selection policies. Bitwig's own sandbox grouping is a different mechanism.

Only `dxvk` and `wined3d` are accepted. Plugg rejects unknown fields, unsupported schemas, path traversal and symlinks that lead outside the prefix. DXVK requires the four core DLLs that the selected Proton build already provides, and Plugg checks their hashes. Selecting graphics never downloads components, rewrites DLLs or touches licences. The session checks and resolves the policy when it starts, then gives each child process its selected DLL overrides. Nothing runs on the audio callback path.

For recipe authors, the supported Python operation is:

```python
from plugg.recipes import configure_graphics
configure_graphics(environment_directory, policy)
```

It works on an existing environment and requires the DAW and applications to be closed. It keeps a small backup of the configuration and launcher in `configuration-history`, and installs a content-addressed copy of the normal session manager. `session.json` stores the policy as `graphics_policy`. Editing a recipe file never changes an existing installation silently. Existing environments without that field keep using their legacy `graphics_backend`. When the field exists, it takes precedence. A new version at the same module path inherits the setting, but not any claim of compatibility. Test again after updates.

The Plugin Alliance profile is preliminary evidence for HG-2 1.10.0.0, MetricAB 1.5.0 and DSM V3 3.7.0.0, with the editor-detach bridge patch (`patches/0002-detach-editor-before-wrapper.patch`) and the guarded UMU-Proton 10.0-4 runtime. It does not install those patches, validate another runtime or claim that every PA plug-in works. DSM curve interaction stays uneven with either renderer. See the [Plugin Alliance compatibility notes](compatibility/plugin-alliance.md) for the test limits.

## Shared archive utility operation (implemented Python interface)

`plugg.archive_component.install(store, prefix, assets, report, check)` prepares Windows archive tools for any helper adapter. The caller chooses the persistent environment, supplies verified package descriptors (`package`, `url`, `sha256`) and holds the environment's installation lock. This is an internal typed operation. It is not a download or command field that public recipes can fill in freely. Klevgrand's `archive_tools` adapter passes it the existing package set.

The operation uses the existing hash-checked download and safe extraction path. It stages the binaries and licence notices, requires `bsdtar.exe` and provides a `tar.exe` alias. Before copying, it checks every package and installed file for conflicts. On a repeat, it accepts identical installed files. It rejects conflicting files and destinations outside the prefix. It records the asset list only on success. It does not select a runtime, launch Wine or change the licensing identity.

This is not a filesystem transaction. An I/O error during copying can leave partial files, so adapters must keep their normal handling for interrupted installs. Fixture tests cover successful preparation, repeats, kept notices, late conflicts, a missing executable and destinations outside the prefix. A real-package check downloads all 13 pinned MSYS2 archives into a disposable cache, produces 48 Windows binaries with their notices, and confirms the output is unchanged on a repeat. It does not launch Wine or a helper. Run it with `python3 scripts/test-archive-component.py`.

`plugg.artifacts` holds the shared artifact transport. `fetch` checks the selected descriptor's SHA-256 before it accepts a download or a cached file. `unpack` does bounded archive extraction with path filtering. Runtime provisioning, VC installation and archive-tool preparation all use this code. Vendor adapters choose the descriptors. This module does not discover packages, resolve versions or allow arbitrary recipe download sources. The older names `recipes.fetch` and `recipes.unpack` remain as aliases.

Cached artifacts get a filename that starts with their SHA-256. Two dependencies with the same upstream filename therefore get separate paths, and preparing one version cannot replace the file an installer is about to use. Plugg copies a verified legacy cache entry, named by basename only, into the new path without downloading it again, and keeps the old entry. Every reuse checks the hash again. This is artifact storage only. It does not mean layered Windows environments.

## Helper entry-point operation (implemented Python interface)

`plugg.helper_component.configure(prefix, full_launcher, spec)` generates the launch files for an existing managed environment. `spec` has exactly three fields:

- `name`,
- `executable`, a literal EXE path relative to `drive_c`,
- `archive_tools`, a boolean.

The archive option adds the fixed private tools directory to the Windows PATH. It does not install the component.

`installed_binary(prefix, spec)` checks that the installed helper exists inside its environment. Klevgrand's adapter uses both operations. Fixture tests cover another helper path, the archive PATH choice, quoted Linux launcher paths, missing targets, and rejection of path traversal and batch expansion.

This interface is narrower than free-form command templates. It cannot express installer arguments, environment allocation, PACE requirements or vendor window workarounds. The public TOML helper operation now uses it. The recipe guide describes which runtimes and dependencies that operation supports. Updating the application source never regenerates the launch files in licensed environments.

The shared environment configurator accepts this description through `recipes.configure(store, job_id, runtime, helper_spec=spec)`. It validates the description before it writes launch files, records it in `helper-entry.json`, and marks the session as `managed-helper-1`. The default Klevgrand path and the disabled-helper path keep their previous session profiles. This interface only prepares the environment for an adapter. The caller still owns environment allocation, idle locking, installer execution and publication. On its own it adds no manager card and does not turn the helper into a supported public recipe. A filesystem fixture tests custom configuration without Wine or a vendor installation.

`helper_component.install(job, prefix, full_launcher, spec, arguments, check)` is the matching operation for saved installers. Immediately before running the installer, it checks the installer and its companion files again. It passes the arguments as a list, runs in the saved payload directory, and checks for the expected helper after a successful exit. It discards vendor output so it does not collect account information. Klevgrand calls it inside its existing window-placement setup. The caller holds the job and environment locks and owns replay prevention, progress, cancellation state and any later component setup.

Fixture tests cover an unchanged split payload, a changed companion file that blocks execution, argument boundaries, installer failure, and a successful exit without the expected helper. The tests simulate the installer processes. This code has not yet been tested with a fresh installation from a real vendor since it was extracted.

## Documenting an integration before automation

Set `documentation_only = true` on a vendor or component definition to publish its requirements and notes before the operations are ready. The flag carries through dependencies. The graphics planner, helper compiler and direct-import compiler reject these graphs. Adding or viewing them applies nothing. Keep executable adapters in place until a separately reviewed migration is ready. [Universal Audio](recipes/universal-audio.md) is an example.

## Shared archive tools

A component may declare `archive_tools = true`. Helper compilation turns that into the shipped, hash-pinned MSYS2 package set and adds the private directory to the helper's PATH. It cannot name arbitrary archives or commands. Only helper setup can run this component. Direct imports and graphics-only application reject it. Klevgrand is the first executable vendor recipe that uses `plugg.windows-archive-tools@2`.

## PowerShell and Native Access

A component may declare `powershell = true` to select the fixed Microsoft PowerShell MSI and the launcher built from source. A reviewed helper may use `helper_profile = "native-access"` with the exact supported executable path. Unreviewed community recipes cannot use these capabilities. [The NI recipe](recipes/native-instruments.md) covers the build steps, lifecycle scope, the explicit login handoff and the validation limits.

A component may declare `ntk_daemon = true` together with the Native Access helper profile. This selects the bundled installer path, checksum and silent argument that the core defines, so recipes cannot supply commands. The component installs after Native Access, checks its service payload and installation record, and starts the service in the same Proton launch as the helper. All prefixes share the daemon's local socket address, so a daemon running in another prefix blocks setup.

### Sharing components across vendors

When the operation and the requirements match, refer to an existing component. For example, the Klevgrand and Universal Audio definitions both require `plugg.windows-archive-tools@2`. The UA definition stays documentation-only until its other setup steps are automated. A vendor name is not a reason to create another copy of a common dependency.

Sharing means reusing the definition, the implementation and the validation. Each Windows environment still gets its own installed files and registry settings. Sharing a component does not mean a shared writable prefix or a layered filesystem.

Keep installer identity, helper launch behaviour and product-specific settings in the vendor recipe. Reuse graphics settings, Windows libraries, extraction tools and compatibility fixes where the requirements match. Test a dependency shared by two vendors with both of them. Sharing a declaration does not prove compatibility.

By default, the catalogue shows the latest revision of each component. Turn on history to see older definitions. Recipes keep resolving their exact pinned revisions.
