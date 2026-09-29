# iLok and PACE

Plug-ins licensed through iLok need PACE License Support, a Windows service plus iLok License Manager. Plugg runs PACE in one shared Windows environment, the iLok environment, and installs every iLok-licensed vendor into it. iLok sees that environment as one computer.

This works on the maintainer's system with UA Connect and UADx LA-2A, eight Soundtoys products and soothe v1, activated through iLok License Manager and opened in Bitwig. It is still experimental. Audio after a reboot, project recall across updates, and vendors beyond these have not been checked.

Plugg installs PACE with the vendor's own unmodified MSI. It never edits PACE, its licence checks or a vendor's binaries.

## Setting it up

You need the PACE 6.0.1 MSI (SHA-256 `1db14119…`). UA Connect downloads it, and so do other vendors' installers.

```sh
plugg runtime assemble plugg-1    # downloads the patched Wine modules, checks their hashes
plugg runtime select plugg-1      # new environments use it
plugg ilok plan PACE.msi          # checks only
plugg ilok create PACE.msi        # builds the iLok environment
```

`ilok create` makes a new prefix on the `plugg-1` runtime and gives it a machine identity derived from this computer. It runs the MSI with `msiexec /qn` and records iLok License Manager as the environment's manager. It refuses an untested PACE version, a library that has not selected `plugg-1`, and an existing iLok environment that still records activations or has programs running. An old environment stays on disk, and `licensing-environments.json` lists it under `previous`.

Then add vendors to it:

```sh
plugg recipe setup-existing plugg.universal-audio@1 --installer UA_Connect_1_10_0_3844_Win.exe \
  --environment ~/.local/share/plugg/environments/ILOK_ENVIRONMENT_ID
plugg recipe setup-existing plugg.softube@2 --installer "Softube Central Setup 3.0.5.exe" \
  --environment ~/.local/share/plugg/environments/ILOK_ENVIRONMENT_ID
plugg ilok install SpaceBlender5_5.5.5.19885_64.exe EchoBoyJr5_5.5.5.19885_64.exe --vendor Soundtoys
```

`plugg ilok status` shows the environment's ID. The [UA](universal-audio.md) and [Softube](softube.md) pages cover those two in detail.

`ilok install` runs the installers one after another, each in its own window, and reports whether PACE's files changed.

## Activating

Activation prompts don't pile up. After an install, Plugg loads only the plug-ins that install added or changed, and each new product may ask for activation once. It doesn't reload plug-ins from earlier installs that are still waiting, and closing UA Connect or Softube Central doesn't reload them either.

When you're ready, run `plugg ilok open` or press **Open iLok** on the card. Activate in iLok License Manager and close it. Plugg then loads every waiting plug-in and publishes the ones that now work. UA Connect and Softube Central have their own cards under the vendor's name, marked as living in the shared iLok environment. `ilok open ua-connect` and `ilok open softube` open them from the command line.

## Keeping the activations

iLok ties an activation to what it sees as the machine. Anything that changes the environment's identity, such as a new runtime, a new prefix or a restored copy, can make it look like another computer. Before any of that, deactivate in iLok License Manager. See [licensing safety](../licensing-safety.md). Record what the environment holds with `plugg licensing protect`, and Plugg refuses identity-changing operations until you record a deactivation.

## Why it needs its own runtime

PACE's installer fails on stock Wine for two reasons, and `plugg-1` carries a source fix for each. [The runtime page](../runtime.md) explains how to get it or build it yourself.

**Windows version.** A managed custom action in the MSI runs inside `rundll32.exe` and sees Windows 6.2, so the installer stops at its launch conditions. Windows' own rundll32 declares the Windows versions it supports in a manifest. The patch gives Wine's rundll32 the same manifest, and code it hosts then sees 10.0. [Patch 0001](../../patches/wine/0001-rundll32-Declare-supported-Windows-versions-in-a-man.patch).

**Service failure actions.** WiX queries `SERVICE_CONFIG_FAILURE_ACTIONS` to preserve a service's recovery settings. Wine's `QueryServiceConfig2W` returns `ERROR_INVALID_LEVEL` for it, which the installer reports as `0x8007007c` before rolling back. The patch makes Wine's service manager store and report failure actions in the registry values Windows uses. Wine still doesn't restart a crashed service. The settings are stored, not acted on. [Patch 0002](../../patches/wine/0002-services-Store-and-report-service-failure-actions.patch).

The fixtures in [diagnostics/msi-version](../../diagnostics/msi-version/) and [diagnostics/service-config](../../diagnostics/service-config/README.md) reproduce both problems without any vendor software.

## What has been checked

1. Clean install in a fresh prefix with the unmodified MSI on `plugg-1`. Done. The service is registered with its failure actions stored as Windows keeps them. On the stock runtime the same MSI rolls back.
2. Service configuration without removing any vendor check. Done, for installation.
3. The PACE service starts, iLok License Manager signs in and activates. Done.
4. UA Connect recognises PACE 6.0.1. Done.
5. An activated plug-in through a service restart, a reboot and a saved project. Partly. Plug-ins open and play in Bitwig. Reboot persistence and project recall are not recorded yet.
6. Mono instead of Microsoft .NET. Not tested.
7. Updating PACE, rolling back, and more vendors. Not tested.

## Limits

- Automatic PACE provisioning from a recipe stays off. `plugg.pace-license-support@1` in the catalogue documents the requirement and cannot install anything. Creating or joining the iLok environment goes through `plugg ilok` only.
- Plugg keeps vendor logs, cached installers, credentials and account state out of Git.
- An environment is not a security sandbox. Everything installed in the iLok environment shares one Windows prefix.
