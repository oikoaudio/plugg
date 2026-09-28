/* Own-code probe for the RtlVirtualUnwind2() NULL writes (Wine a55cddce98).
 *
 * Wine's exception dispatcher unwinds collided frames by calling
 * RtlVirtualUnwind2() with no handler data and no handler output. Unpatched,
 * it stores the "no handler" result through that NULL handler pointer, and
 * the fault it raises recurses until the stack is gone. This probe makes the
 * same call on its own frame. It writes "started" to C:\unwind-probe.txt
 * first and "survived" once the call returns, so "started" alone is the bug
 * and no file means it never ran.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include <windows.h>
#include <rtlsupportapi.h>

int mainCRTStartup(void) {
    CONTEXT context;
    DWORD64 base = 0;
    ULONG_PTR frame = 0;
    BOOLEAN machine_frame = FALSE;
    DWORD written;
    HANDLE output = CreateFileW(L"C:\\unwind-probe.txt", GENERIC_WRITE, FILE_SHARE_READ, 0, CREATE_ALWAYS,
                                FILE_ATTRIBUTE_NORMAL, 0);
    WriteFile(output, "started\r\n", 9, &written, 0);
    FlushFileBuffers(output);
    __try {
        RtlCaptureContext(&context);
        PRUNTIME_FUNCTION function = RtlLookupFunctionEntry(context.Rip, &base, NULL);
        if (!function) {
            WriteFile(output, "no unwind data\r\n", 16, &written, 0);
            ExitProcess(3);
        }
        RtlVirtualUnwind2(UNW_FLAG_NHANDLER, base, context.Rip, function, &context, &machine_frame,
                          NULL, &frame, NULL, NULL, NULL, NULL, 0);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ExitProcess(4);
    }
    WriteFile(output, "survived\r\n", 10, &written, 0);
    CloseHandle(output);
    ExitProcess(0);
}
