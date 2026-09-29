# Draft upstream patch to detach the Wine editor before destroying its X11 wrapper

This patch is ready for review and has not been submitted upstream. The patch is `patches/0002-detach-editor-before-wrapper.patch`, based on upstream commit `b580a9f7fc46509767ca156d4f92872552b9e571`. It does not depend on this project's managed-runtime patch and contains no Plugg-specific policy or identifiers.

## Problem and change

In Bitwig on X11/XWayland, closing some Windows VST3 editors causes a fatal `BadWindow` / `X_ChangeProperty` error, or stops the editor from reopening.

`Editor` declares `wrapper_window_` after `win32_window_`. C++ destroys members in reverse order, so the X11 wrapper is destroyed and flushed before `DeferredWin32Window` tries to rescue its Wine child by reparenting it to the root window. When X11 destroys a parent window, it also destroys child windows that belong to another client.

The patch adds an explicit `Editor` destructor. It unmaps the current Wine window and finishes a checked reparent before the members are destroyed. The existing deferred `WM_CLOSE` behaviour stays. The patch does not suppress Wine X errors, and it does not change the audio transport, process grouping, graphics selection or licensing.

## Evidence

The two-client fixture in `diagnostics/hg2-close/window-order.c` creates only disposable, unmapped windows. Destroying the parent first produced `BadWindow` for `ChangeProperty` in 100 of 100 cycles. Detaching first produced it in 0 of 100.

To compile and run it against an available X11 display:

```sh
cc -Wall -Wextra -Werror diagnostics/hg2-close/window-order.c -lxcb -o /tmp/window-order
/tmp/window-order
```

This proves the X11 lifetime mechanism. It does not prove the full cause of any plug-in failure. Manual checks on CachyOS, Hyprland/XWayland, Bitwig and UMU-Proton 10.0-4 gave these results:

| Plug-in | Result with the patch |
| --- | --- |
| Black Box HG-2 | Close and reopen worked, also during playback and with two instances |
| Pro Audio DSP DSM V3 | Close and reopen worked with WineD3D and DXVK. Curve interaction is still jumpy. |
| ADPTR MetricAB | Usable, and close and reopen worked with DXVK. With WineD3D it still hung. |
| bx_masterdesk, bx_oberhausen, bx_opto | Parameter controls, close and reopen worked |
| Shadow Hills Mastering Compressor | Parameter controls, close and reopen worked |

These are preliminary manual checks. Nobody recorded cycle counts or long session times. HG-2's editor is still black under DXVK, with or without this patch. MetricAB's hang under WineD3D happens inside the plug-in's own removal call, before this destructor runs. Do not claim that the detach patch alone fixes either issue. The runtime also had an unrelated ole32 foreign-window guard, but that guard was already in place when the Plugin Alliance teardown problem appeared.

## Review questions and outstanding validation

- Test other DAWs, plug-ins that already work, window destruction started by the host, editor resizing, and fast close and reopen before the deferred timer fires.
- Check that unmapping does not break plug-ins that dislike hidden windows, and that the idle timer cannot re-enter during teardown.
- The existing deferred destructor still tries to reparent later. Should that become one shared, explicit detach operation?
- The explicit destructor does not handle cleanup after a constructor failure.
- Check the behaviour when the plug-in or host has already destroyed or replaced the underlying X11 window, including the existing catch-and-continue path.
- This local build is VST3-only. VST2 and CLAP are untested.

Do not present this as a fix for all Plugin Alliance plug-ins. The patch is small and the evidence justifies a review, but wider regression testing is still needed.

## CLAP needs patch 0005 with it

The destructor this patch adds to `Editor` removes the move constructor the compiler would otherwise generate. VST2 and VST3 never move an editor, but yabridge's CLAP host moves a temporary plug-in instance into its instance map, and that instance holds an `std::optional<Editor>`. With CLAP switched on, `src/wine-host/bridges/clap.cpp` then fails to compile, with any GCC. Patch `0005-clap-construct-instance-in-place.patch` builds the instance in place with `try_emplace`, so nothing is moved. Giving `Editor` a move constructor would be the other fix, but a moved-from editor's destructor would then run the X11 detach on a window it no longer owns. An upstream submission of this patch should include 0005.

## Local build and deployment

`scripts/build-bridge.sh` checks the pinned upstream tree against the ordered `patches/*.patch` series. It applies any recorded patches that are missing from the end of the series and refuses unknown local source changes. `build.json` records the upstream revision, every patch hash and every artifact hash. This records where the source and build came from. It does not claim that different toolchains produce identical binaries.

Build into a separate output directory before you touch a working installation:

```sh
PLUGG_BRIDGE_OUTPUT=bundle/bridge-detach-v1 scripts/build-bridge.sh
```

The default output is still `bundle/bridge`. Do not rebuild into a shared bundle that a running DAW is using. Published plug-ins do not link into the build directory. Each bundle links its three bridge files into a content-addressed release inside the library, `bridge-releases/<hash>`. Which release a bundle uses does not affect its Windows module links, class IDs, prefix or renderer settings. Do not delete a release while any publication refers to it.

To roll out a new build, build it and then publish or relink against the new release (see [deployment troubleshooting](../deployment-troubleshooting.md#bridge-links-into-a-moved-checkout)). Do not edit links by hand, and run the regression checks above first. Running the build alone moves no existing publication.
