# Cytomic

The Glue **installs and opens but cannot be authorised** on the maintainer's system (Bitwig, Hyprland/XWayland, NVIDIA, UMU-Proton 10.0-4 `plugg-1`). Its authorisation window is black, and it crashes the plug-in host. Until someone finds a fix, expect The Glue to stay unauthorised under Plugg. This is a negative finding from one afternoon of testing on 2026-09-29, not a full investigation.

## Tested product

| Product | Version | Result |
| --- | --- | --- |
| The Glue | 1.9.3 (VST3, 64-bit) | Installs from Cytomic's Inno Setup installer. Loads in Bitwig, and the editor opens and draws. Authorisation fails as described below. Audio, presets and project recall were not checked. |

The environment is a standard installer environment with DXVK graphics. Plugg has no Cytomic recipe.

## What happens

The Glue is a JUCE 8 plug-in that can draw with Direct2D. Its main editor works because Cytomic's own `Documents/Cytomic/The Glue/Settings.xml` has `UiSoftwareRender` set to `true`.

Clicking "Authorise..." opens a separate top-level window titled "The Glue Authorisation" (600×552). It has the challenge code for manual authorisation and the automatic authorisation form.

- The first time the maintainer opened it, the window stayed black but open.
- Later, a single key press in the black window crashed the plug-in host. Ctrl alone was enough.
- Later still, the window crashed the host within seconds of opening, with no input. Nobody has found out what changed between these attempts. The Glue keeps nothing in the registry apart from its uninstall entry, and nothing in its files except `Settings.xml`, whose settings stayed the same.

Every crash writes the same lines to the host's Wine output:

```
err:ole:com_get_class_object class {aa509086-5ca9-4c25-8f95-589d3c07b48a} not registered   (four times)
err:seh:user_callback_handler ignoring exception c0000005
err:virtual:virtual_setup_exception stack overflow 4992 bytes addr 0x6ffffff835aa stack 0x1fc80 (0x20000-0x21000-0x120000)
```

The stack overflow happens on the window's thread, which points at unbounded recursion in window or input handling rather than at drawing. The missing COM class is probably Windows' Virtual Desktop Manager, which JUCE asks about for top-level windows. That identification is from memory and unchecked, and the failed lookup may be harmless.

## What was ruled out

| Change | Result |
| --- | --- |
| WineD3D instead of DXVK, for the whole environment | The editor stops redrawing and ignores the mouse. Bitwig reports that the plug-in host is not responding. |
| REAPER instead of Bitwig | The crash takes REAPER down, because REAPER loads the plug-in in its own process. |
| Element 1.1.1 for Linux | Crashes while loading The Glue. |
| A Wine virtual desktop (1280×900) for the environment | Wine's desktop window appears, but the crash stays the same. |
| Element 1.1.1 for Windows, installed in The Glue's environment, loading the VST3 directly without yabridge | Crashes too. |

The Windows Element result means the bridge is not the cause. The problem sits between The Glue and this Wine/Proton build.

## Not tried yet

- Reading the challenge code with UI Automation while the window is open. The test built a small reader for this, but it ran after the window had already crashed.
- A different Wine build, for example the distribution's Wine or a newer Proton, in a throwaway prefix.
- Asking Cytomic about authorising a machine running Wine.

## Licensing notes

Cytomic's manual route needs the challenge code from the black window. You copy the code, paste it next to the licence under My Account on cytomic.com, download an authorisation file and drag it onto the plug-in.

The binary contains JUCE's machine-identifier code: `SOFTWARE\Microsoft\Cryptography` `MachineGUID`, SMBIOS through `GetSystemFirmwareTable`, the volume serial and the network adapters' MAC addresses. Which of these Cytomic uses is unknown. Under Wine, the MachineGuid and the volume serial belong to the prefix, and the SMBIOS serial numbers are missing because Linux lets only root read them. An authorisation made in a native Windows install on the same computer will therefore probably not match a Plugg environment.

If a way to authorise turns up, protect the environment afterwards with `plugg licensing protect`, as for any environment that holds an activation. See [licensing safety](../licensing-safety.md).
