/* SPDX-License-Identifier: GPL-3.0-or-later
 * Own-code service-configuration fixture for the PACE installer blocker.
 * It creates and deletes one scratch service. Run only in a disposable prefix. */
#include <windows.h>
#include <winsvc.h>

static HANDLE output;
static void line(const char *text) {
    DWORD written;
    WriteFile(output, text, lstrlenA(text), &written, 0);
    FlushFileBuffers(output);
}
static void result(const char *what, DWORD level, BOOL ok, DWORD error, DWORD needed) {
    char text[200];
    wsprintfA(text, "%s level %lu: %s error=%lu needed=%lu\r\n", what, level, ok ? "ok" : "FAILED", ok ? 0 : error, needed);
    line(text);
}

static int contains(const WCHAR *s, const WCHAR *needle) {
    for (; *s; s++) { const WCHAR *a = s, *b = needle; while (*a && *b && *a == *b) { a++; b++; } if (!*b) return 1; }
    return 0;
}

static const char *names[] = {"", "DESCRIPTION", "FAILURE_ACTIONS", "DELAYED_AUTO_START_INFO",
    "FAILURE_ACTIONS_FLAG", "SERVICE_SID_INFO", "REQUIRED_PRIVILEGES_INFO", "PRESHUTDOWN_INFO",
    "TRIGGER_INFO", "PREFERRED_NODE"};

static void query(SC_HANDLE service, DWORD level) {
    static BYTE buffer[4096];  /* static: no stack probe without a C runtime */
    DWORD needed = 0;
    SetLastError(0);
    /* A probe with no buffer is how most callers size the real call. */
    BOOL ok = QueryServiceConfig2W(service, level, 0, 0, &needed);
    DWORD error = GetLastError();
    result("query-size", level, ok, error, needed);
    SetLastError(0);
    ok = QueryServiceConfig2W(service, level, buffer, sizeof(buffer), &needed);
    result("query", level, ok, GetLastError(), needed);
    if (ok && level == SERVICE_CONFIG_FAILURE_ACTIONS) {
        SERVICE_FAILURE_ACTIONSW *a = (SERVICE_FAILURE_ACTIONSW *)buffer;
        char text[200];
        wsprintfA(text, "  reset=%lu actions=%lu\r\n", a->dwResetPeriod, a->cActions);
        line(text);
        wsprintfA(text, "  reboot=%ls command=%ls\r\n", a->lpRebootMsg ? a->lpRebootMsg : L"(none)",
                  a->lpCommand ? a->lpCommand : L"(none)");
        line(text);
        for (DWORD i = 0; i < a->cActions; i++) {
            wsprintfA(text, "  action %lu: type=%u delay=%lu\r\n", i, a->lpsaActions[i].Type, a->lpsaActions[i].Delay);
            line(text);
        }
    }
    if (ok && level == SERVICE_CONFIG_FAILURE_ACTIONS_FLAG) {
        char text[80];
        wsprintfA(text, "  non-crash=%d\r\n", ((SERVICE_FAILURE_ACTIONS_FLAG *)buffer)->fFailureActionsOnNonCrashFailures);
        line(text);
    }
}

static void change(SC_HANDLE service, DWORD level) {
    SC_ACTION actions[3] = {{SC_ACTION_RESTART, 60000}, {SC_ACTION_RESTART, 60000}, {SC_ACTION_NONE, 0}};
    SERVICE_FAILURE_ACTIONSW failure = {86400, (WCHAR *)L"Fixture reboot", (WCHAR *)L"fixture.exe --recover", 3, actions};
    SERVICE_DESCRIPTIONW description = {(WCHAR *)L"Plugg fixture"};
    SERVICE_DELAYED_AUTO_START_INFO delayed = {TRUE};
    SERVICE_FAILURE_ACTIONS_FLAG flag = {TRUE};
    SERVICE_SID_INFO sid = {1}; /* SERVICE_SID_TYPE_UNRESTRICTED */
    SERVICE_REQUIRED_PRIVILEGES_INFOW privileges = {(WCHAR *)L"SeChangeNotifyPrivilege\0"};
    SERVICE_PRESHUTDOWN_INFO preshutdown = {180000};
    void *data[] = {0, &description, &failure, &delayed, &flag, &sid, &privileges, &preshutdown, 0, 0};
    if (!data[level]) {
        line("change level skipped: no sample data\r\n");
        return;
    }
    SetLastError(0);
    BOOL ok = ChangeServiceConfig2W(service, level, data[level]);
    result("change", level, ok, GetLastError(), 0);
}

void mainCRTStartup(void) {
    output = CreateFileW(L"C:\\service-config.txt", GENERIC_WRITE, FILE_SHARE_READ, 0, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, 0);
    SC_HANDLE manager = OpenSCManagerW(0, 0, SC_MANAGER_ALL_ACCESS);
    if (!manager) { line("OpenSCManager failed\r\n"); ExitProcess(2); }
    SC_HANDLE service = OpenServiceW(manager, L"PvbFixtureService", SERVICE_ALL_ACCESS);
    /* --reopen: read what an earlier --keep run stored, after the service manager restarted. */
    if (contains(GetCommandLineW(), L"--reopen")) {
        if (!service) { line("reopen: service missing\r\n"); ExitProcess(4); }
        line("== reopened\r\n");
        query(service, SERVICE_CONFIG_FAILURE_ACTIONS);
        query(service, SERVICE_CONFIG_FAILURE_ACTIONS_FLAG);
        DeleteService(service);
        line("done\r\n");
        ExitProcess(0);
    }
    if (service) { DeleteService(service); CloseServiceHandle(service); }
    service = CreateServiceW(manager, L"PvbFixtureService", L"Plugg fixture service",
                             SERVICE_ALL_ACCESS, SERVICE_WIN32_OWN_PROCESS, SERVICE_DEMAND_START,
                             SERVICE_ERROR_NORMAL, L"C:\\windows\\system32\\notepad.exe", 0, 0, 0, 0, 0);
    if (!service) { line("CreateService failed\r\n"); ExitProcess(3); }
    for (DWORD level = 1; level <= 9; level++) {
        char text[80];
        wsprintfA(text, "== %lu %s\r\n", level, names[level]);
        line(text);
        query(service, level);
        change(service, level);
        query(service, level);
    }
    if (!contains(GetCommandLineW(), L"--keep")) DeleteService(service);
    CloseServiceHandle(service);
    CloseServiceHandle(manager);
    line("done\r\n");
    ExitProcess(0);
}
