# Plugin Alliance

Plugin Alliance support is **experimental.** Several products work on the maintainer's system (Bitwig, Hyprland/XWayland). They need a bridge fix for closing editors and a renderer choice per plug-in. The results are preliminary manual checks for specific products. They do not cover the whole catalogue.

## Setup

- The tested installer is `pa_installation_manager_win_1_4_0.zip`, SHA-256 `0ff7eca91d657e0e16c470dd260548b3bb3576c3c489905fe5c2a7f84b3eb8c5`. It contains `PA-InstallationManager-v1.4.0.msi`.
- Plugin Alliance gets its own prefix on UMU-Proton 10.0-4 with the [OLE32 foreign-window guard](universal-audio.md#editor-close-crash-and-the-ole32-guard). Helper and plug-in launches use the same build. It does not share the iLok/PACE environment.
- The first MSI run can exit without showing a window, yet still install the manager. Running it again offers repair or remove. A silent exit does not mean installation failed. The manager is at `C:\Program Files\Plugin Alliance\Installation Manager\PA-InstallationManager.exe` and opens floating on Hyprland.
- The vendor card has **Open PA Manager** and **Refresh library**. Install products in the manager, close it, then refresh.
- Plugin Alliance activates products per device. Treat the prefix as a machine, and do not recreate or clone it once products are activated.

## Tested products

| Product | Version | Renderer | Bridge fix | Result |
| --- | --- | --- | --- | --- |
| Black Box Analog Design HG-2 | 1.10.0.0 | WineD3D | editor detach | Editor close and reopen work, also during playback and with two instances. The editor is black with DXVK. |
| ADPTR MetricAB | 1.5.0 | DXVK | editor detach | Controls, close and reopen work. With WineD3D the editor hung on close. |
| Pro Audio DSP DSM V3 | 3.7.0.0 | DXVK | editor detach | Close, reopen and ordinary controls work. Dragging curve nodes is jumpy with either renderer. |
| bx_masterdesk | 1.8.0.0 | WineD3D | editor detach | Close, reopen and parameter controls work. Without the fix it crashed on editor close. |
| bx_oberhausen | not recorded | WineD3D | editor detach | Close, reopen and parameter controls work |
| bx_opto | not recorded | WineD3D | editor detach | Close, reopen and parameter controls work |
| Shadow Hills Mastering Compressor | not recorded | WineD3D | editor detach | Close, reopen and parameter controls work. Without the fix it crashed on editor close. |
| TBTECH Kirchhoff-EQ | not recorded | DXVK, local override | none | Usable. A faint black flicker appears when moving between the header and EQ areas. |

Other PA products, including the Unfiltered Audio range, Vertigo VSM-3 and ADPTR StreamLiner, were discovered and published but not checked one by one. Automation, state recall, long sessions and other DAWs are untested for all of them.

`plugg/recipes/plugin-alliance-graphics.json` holds the renderer choices for HG-2, MetricAB and DSM V3, with WineD3D as the default. Kirchhoff's DXVK setting is an override applied to one installation. It is not part of the bundled profile. [Recipe authoring](../recipe-authoring.md#implemented-graphics-policy-fragment) explains how these profiles work.

## The editor-close detach fix

Closing some editors in Bitwig either hung the plug-in host or killed it with an X11 `BadWindow` error on `X_ChangeProperty`. The cause is the order in which yabridge's editor destroys its members. `wrapper_window_` is declared after `win32_window_`, so it is destroyed first. Destroying the X11 wrapper also destroys the embedded Wine child window, which belongs to another X client. The deferred step that should first move that child to the root window runs too late.

A two-client XCB fixture uses only disposable, unmapped windows. Destroying the parent first reproduces `BadWindow` on `ChangeProperty` in 100 of 100 cycles. Reparenting the child first gives 0 of 100. This shows the X11 mechanism. It says nothing about any plug-in's compatibility.

The fix adds an explicit editor destructor. It unmaps the current Wine window and detaches it synchronously before the members are destroyed. It keeps the deferred `WM_CLOSE` behaviour and does not suppress Wine X errors. The fix is patch `0002-detach-editor-before-wrapper.patch` in Plugg's bridge patch series and is ready for upstream review. See [the upstream write-up](../upstream/yabridge-editor-detach.md). The fixture is in `diagnostics/hg2-close`. A recipe can require the fix per module through the `plugg.bridge-editor-detach@1` component, as `plugg.plugin-alliance@2` does.

## Renderer findings

- HG-2 shows a black editor with DXVK, with or without the detach fix. WineD3D works. With Direct2D disabled, the module fails to load, and no other usable renderer was found.
- MetricAB hangs on editor close with WineD3D. The host's UI thread waits inside the plug-in's own editor removal (`IPlugView::removed()`), before the detach fix runs. With DXVK and the detach fix, it works. Nobody has identified the object it waits for.
- DSM V3 curve dragging feels equally jumpy with WineD3D and DXVK. Nobody has worked out whether input handling or redraw speed causes it.
- These results support choosing the renderer per plug-in rather than per vendor.

## Known issues

- DSM V3 curve-node dragging is jumpy and imprecise.
- Kirchhoff-EQ flickers faintly around the header/EQ boundary. An earlier report of stronger flicker came from an older plain-Wine copy of the same plug-in, not from Plugg's publication. Before you report a renderer problem, check which copy your DAW loaded. The Bitwig log shows the path.
- If you have an older yabridge/Wine installation of the same products, remove or disable its wrappers, for example under `~/.vst3/yabridge`, so the DAW does not load both. Plugg does not manage those wrappers.

## Validation limits

Factory discovery and publication are automated. All editor and control results above are manual checks. Nobody recorded cycle counts, playback conditions or session lengths, and none of it counts as heavy or long-session testing. This page makes no claim for other DAWs, other runtimes or products not listed.
