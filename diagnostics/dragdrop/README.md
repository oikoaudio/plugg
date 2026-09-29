# OLE drag-and-drop lifetime fixture

This is an own-code diagnostic for the LA-2A editor-close investigation. It requires no commercial plug-in or license. Use only a disposable prefix, because the foreign-process mode deliberately triggers a crash. Never use an activated environment for this fixture.

Build with `sh diagnostics/dragdrop/build.sh`. This uses Clang/lld and the installed Wine Windows headers and import libraries. The build is not yet a pinned toolchain artifact. Binary output goes to `build/diagnostics`, which git ignores.

Run `dragdrop.exe` inside the disposable Windows runtime. With no arguments it creates an unshown window and a reference-counted IDropTarget, then performs 100 cycles of RegisterDragDrop and RevokeDragDrop. After each cycle, the reference count must return to one. It writes `C:\fixture-parent.txt`.

Run `dragdrop.exe --foreign` to repeat the baseline, register the target, and create a child process that calls RevokeDragDrop on the parent's window. The target is allocated at a fixed parent-only address to make invalid cross-process dereferencing observable. Failure to allocate this address is a fixture setup failure, not the bug. The child writes `C:\fixture-child.txt`. The parent waits up to 15 seconds, then stops only its own test child if necessary, and checks owner-side cleanup. Run a single fixture instance at a time because the window name is fixed.

## Observed on UMU-Proton-10.0-4

- In normal mode, the fixture exited 0 and all 100 cycles passed.
- In foreign mode, the parent registered the target. The child saw the parent's property pointer at `0x500000000000`, then exited 1 before logging a RevokeDragDrop result. Parent-side cleanup succeeded and the reference count returned to one. The parent's exit code 10 reports the child's failure.
- The local disposable prefix and logs are in `/tmp/plugg-dragdrop`. They contain no user activation data.

This demonstrates a cross-process failure case in this runtime. It does **not** yet prove that LA-2A revokes a foreign window or that this fixture's exit path exactly matches LA-2A's. LA-2A's separate debugger capture found an unmapped property pointer at RevokeDragDrop+0x66, immediately before IDropTarget::Release. Pointer lifetime and window ownership must be checked on the real case.

## Candidate fix and validation gates

Investigate rejecting foreign-process revocation before reading process-local target pointers, like Wine's ownership check in RegisterDragDrop. Confirm expected behavior on Windows and trace LA-2A's window owner before selecting the return code or claiming this fixes LA-2A. A stale same-process pointer requires a different lifetime correction.

Do not replace RevokeDragDrop with a no-op or skip all Release calls. A fix must preserve normal release counts, registrations and real drag-and-drop. Build a source patch against the selected runtime and test this fixture, then repeat real editor open and close cycles, audio and state recall. Keep a separate build for the experiment; do not overwrite the shared runtime during a session.

Separately, investigate bridge supervision when the main Windows thread exits but workers survive. A check that only asks whether the process exists misses that failure. The aim is for the host to fail on its own instead of leaving the DAW waiting indefinitely. That does not replace a fix for the fault that started it.

References: Wine `dlls/ole32/ole2.c` RegisterDragDrop/RevokeDragDrop and Microsoft's RevokeDragDrop API documentation. For the tested runtime, the disassembly of the deployed DLL is the authoritative reference.


The later LA-2A ownership capture confirmed that the faulting HWND and IDropTarget pointer both belonged to msedgewebview2.exe. See the UAD compatibility notes for the matched observations. `window-owners.c` inventories these properties without dereferencing them, using EnumWindows/EnumChildWindows, GetPropW, GetWindowThreadProcessId and QueryFullProcessImageNameA. It writes C:\Plugg\drop-owners.txt in the chosen prefix and makes no window or registration changes.

`foreign-revoke-candidate.patch` is a proposed Wine source change, not a deployed fix. The proposed error code follows RegisterDragDrop's foreign-window rejection; Windows reference validation is still required. Apply against a reviewed matching Wine source revision before building; do not mix an arbitrary newer ole32 DLL into the active runtime.


## Source-built guard A/B validation

The x86_64 Windows ole32 module was built from Wine revision `b8fdff8e1f855b5276ec4ddca0f31b2792554322`, the Wine submodule referenced by UMU-Proton-10.0-4. Source archive, patch and artifact hashes plus tool versions are recorded in `guard-build-validation.json`. Full commands and logs and the private reflinked runtime are under ignored `.scratch/wine-ole32`. This is a local diagnostic build, not a bit-for-bit reproduction of Valve's toolchain.

The unpatched control, built from the same source with the same toolchain, produced a child access violation (`0xc0000005`) on foreign revocation. The patched build returned `DRAGDROP_E_INVALIDHWND` (`0x80040102`), and the child exited 0. Both builds passed the 100 normal register and revoke cycles, the owner cleanup and the reference-count check. After the control run, the patched DLL was restored and the patched run repeated, and it passed again.

The build sequence is to extract the pinned source, apply the candidate patch, run autoreconf, generate the Vulkan headers with the source's make_vulkan script and its pinned registry version, run tools/make_specfiles, configure with the recorded flags, and build `dlls/ole32/x86_64-windows/ole32.dll` with make -j4. The first configure attempt finds that the generated headers are missing. Once the headers exist, configuration completes. Install the resulting DLL only into a private copy of the matching runtime. Standalone validation used a disposable prefix; the licensed environment remains unchanged pending the real plug-in test.

Validation is still outstanding for Windows reference behavior, real drag-and-drop operation, repeated LA-2A editor cycles, other vendors, and recall after a reboot and in a saved project. Do not describe this as an upstream-accepted or production-complete patch.
