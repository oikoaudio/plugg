# Universal Audio reusable setup

`plugg.universal-audio@1` describes the UA Connect setup. It also offers a guarded `setup-existing` adapter, which adds UA Connect to a shared PACE environment you have already prepared. Generic new-environment installation rejects this graph, because PACE comes from `plugg ilok create` (see [iLok and PACE](pace.md)). The adapter has joined UA Connect 1.9.6 to an iLok environment built that way, and `plugg ilok update-ua-connect` updated it to 1.10.

The findings behind this recipe are in [the UA compatibility notes](../compatibility/universal-audio.md).

## Reusable requirements

| Component | What it does | Automation status |
| --- | --- | --- |
| PACE / iLok License Support | Shared services and License Manager for the products that share one environment | Diagnostic setup only. Clean provisioning is still blocked. |
| Windows archive tools | Extraction tools on the helper's Windows PATH | The shared component stages the pinned tools and notices, then the UA adapter copies missing files. |
| UA Connect helper compatibility | Helper graphics arguments, consent to disable Electron's sandbox, window placement, process cleanup and library refresh | The setup adapter reuses the existing launcher after consent and prerequisite checks. |
| OLE32 foreign-window guard | Fixes the LA-2A editor-close crash | Checks exact runtime and prefix files. Does not install the patch. |

PACE does not depend on UA Connect. Soundtoys SpaceBlender and soothe v1 work in the same PACE environment without UA's archive tools or helper flags. The OLE32 guard is a separate editor fix, not a licensing component. This definition does not claim that every UAD product needs it.

See also [PACE investigation and automation gates](pace.md).

## Existing machine identity

Publishing, browsing or editing these definitions does not apply them. The recipe planner rejects documentation-only graphs before it touches an environment. Generic helper and direct-import compilation reject such dependencies too. The separate `setup-existing` entry point checks the prepared environment you select. It does not provision dependencies. Defining a recipe migrates no prefix, registry, runtime, launcher, licensing record or installed setup.

Before any repair, replacement, cloning or reprovisioning that could change the machine identity, stop. Open iLok License Manager and deactivate every licence on the affected machine first. Do not rely on an earlier check or a filesystem snapshot to tell you it is deactivated. Defining a recipe does not authorize anyone to apply it.

## Catalogue coverage

The catalogue is a collection of reusable definitions, not a list of installed environments. Klevgrand has an executable modular recipe that installs Helper in a fresh environment. Native Instruments has a modular recipe with its login and service adapter. Other vendors that work need their real setup history reviewed before anyone publishes equivalent definitions. Do not invent requirements from vendor names. A missing catalogue entry does not mean a missing installation.

## How the adapter works

The adapter accepts two reviewed installers. `UA_Connect_1_9_6_3797_Win.exe` has SHA-256 `1d4b1c8e6f64abba2570c76e100132b268220630ac7786c13f8a0ff8c39a55d5` (308,186,200 bytes), and the 396 files it extracts match a working UA Connect installation. `UA_Connect_1_10_0_3844_Win.exe` has SHA-256 `cac93d13c1cbc7415db22932fb085525677f33cef3ea9df844170741087d56af` (314,303,768 bytes). Extraction runs no Windows installer and no bundled PACE setup.

The adapter is built from these reusable operations:

- `vendor_payload.unpack` makes a private copy, checks the pinned hash and size, and stages files with bounded libarchive extraction. Softube uses it too.
- `windows_service` registers a fixed service specification defined in code, and checks it. Softube uses it too. UA needs `UAHelperService`, the installed x64 `uahelperservice.exe`, LocalSystem and automatic start. If a different service with that name exists, the operation refuses.
- `licensed_setup` handles identity and PACE snapshots, keeps destination paths inside the environment and checks that the environment is idle. Softube uses it too.
- `archive_component.install` provides the same pinned archive binaries and licence notices that other helpers use (revision 2).
- `ua_connect.configure` and its lifecycle and publication path run after you give explicit consent for the Electron compatibility flags, or reuse consent already recorded for this exact helper behaviour.

In a new disposable, unlicensed prefix, the adapter assembles the payload and archive component and registers the service once. An unchanged repeat changes nothing. It configures the managed launcher and leaves no Windows programs running. It copies no account or PACE data and requests no activation. This tests preparation and service registration, not login or licensing. To reproduce it:

```sh
python3 scripts/test-ua-setup.py \
  --runtime-environment /path/to/working-runtime-environment \
  --installer /path/to/UA_Connect_1_9_6_3797_Win.exe
```

The script only reads the runtime and launcher configuration. It creates a fresh prefix and leaves its log and result for you to inspect. Unit tests cover installation and repeat with synthetic files, refusal of different files, missing consent, service failure, unknown installers and service-command validation.

## Running it

```sh
python3 -m plugg recipe setup-existing plugg.universal-audio@1 \
  --installer "$HOME/Downloads/UA_Connect_1_9_6_3797_Win.exe" \
  --environment /path/to/an/explicitly-selected/prepared-environment
```

The environment must already have a protected, matching PACE identity, and the OLE32 patch in its runtime and prefix. This operation never installs or replaces either. It does the following:

- stages all vendor and support files,
- refuses conflicting existing files,
- copies only missing files,
- registers the service if it is missing,
- configures the managed launcher.

It does not launch UA Connect, transfer activations or update installed plug-ins.

For a new helper configuration, `--allow-electron-no-sandbox` gives explicit permission for UA Connect's compatibility flags. They affect the helper only, and Wine does not act as a security boundary in their place. Plugg can reuse consent you gave before. Viewing or comparing the recipe never asks for consent.

Do not rebuild a working iLok environment to test this. The next end-to-end check needs a test environment prepared for it, a login and a product installation. Keep track of any activation it uses.

## Updating UA Connect

UA Connect cannot update itself under Wine. Its updater (electron-updater) checks the downloaded installer's Authenticode signature by running `powershell.exe Get-AuthenticodeSignature`. It gets no output and stops with `Unexpected end of JSON input`, which you can see in `AppData/Local/Universal Audio/Logs/UA Connect.log`. Installing PowerShell would not be enough, because Wine's signature check would still not report a valid signature.

`plugg ilok update-ua-connect <installer>` updates UA Connect without running the installer. It does the following:

1. Unpacks the payload of a reviewed version. This contains app files only. Neither 1.9.6 nor 1.10.0 carries a PACE installer.
2. Takes a licensing recovery point.
3. Replaces only the files under `Program Files/UA Connect` that differ.
4. Checks that PACE and the environment's identity have not changed.

Run the same command with an older reviewed installer to roll back. `plugg/ua_setup.py` lists the reviewed versions. For a new UA Connect release, check its payload, then add its hash and size there.
