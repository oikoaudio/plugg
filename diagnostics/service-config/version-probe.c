/* SPDX-License-Identifier: GPL-3.0-or-later
 * Own-code probe loaded by rundll32: reports the Windows version code inside
 * rundll32 is told. Installer custom actions hosted there make the same check. */
#include <windows.h>
#include <winternl.h>

NTSTATUS WINAPI RtlGetVersion(RTL_OSVERSIONINFOEXW *);

void CALLBACK Probe(HWND window, HINSTANCE instance, LPSTR arguments, int show) {
    OSVERSIONINFOW legacy = {sizeof(legacy)};
    RTL_OSVERSIONINFOEXW native = {sizeof(native)};
    char text[200];
    DWORD written;
    (void)window; (void)instance; (void)arguments; (void)show;
    GetVersionExW(&legacy);
    RtlGetVersion(&native);
    HANDLE output = CreateFileW(sizeof(void *) == 8 ? L"C:\\rundll32-version64.txt" : L"C:\\rundll32-version32.txt",
                                GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    int n = wsprintfA(text, "GetVersionEx=%lu.%lu.%lu RtlGetVersion=%lu.%lu.%lu\r\n",
                      legacy.dwMajorVersion, legacy.dwMinorVersion, legacy.dwBuildNumber,
                      native.dwMajorVersion, native.dwMinorVersion, native.dwBuildNumber);
    WriteFile(output, text, n, &written, 0);
    CloseHandle(output);
}
