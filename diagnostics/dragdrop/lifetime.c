/* SPDX-License-Identifier: GPL-3.0-or-later
 * Own-code OLE lifetime fixture. Run only in a disposable prefix. */
#define COBJMACROS
#include <windows.h>
#include <ole2.h>

static LONG refs;
static HANDLE output;
static HRESULT WINAPI query(IDropTarget *self, REFIID iid, void **out) {
    *out=0;
    if ((iid->Data1!=0 && iid->Data1!=0x122) || iid->Data2 || iid->Data3 ||
        iid->Data4[0]!=0xc0 || iid->Data4[7]!=0x46) return E_NOINTERFACE;
    for(int i=1;i<7;i++) if(iid->Data4[i])return E_NOINTERFACE;
    *out=self; InterlockedIncrement(&refs); return S_OK;
}
static ULONG WINAPI addref(IDropTarget *self) { (void)self; return InterlockedIncrement(&refs); }
static ULONG WINAPI release(IDropTarget *self) { (void)self; return InterlockedDecrement(&refs); }
static HRESULT WINAPI enter(IDropTarget *s,IDataObject *d,DWORD k,POINTL p,DWORD *e) { (void)s;(void)d;(void)k;(void)p;*e=0;return S_OK; }
static HRESULT WINAPI over(IDropTarget *s,DWORD k,POINTL p,DWORD *e) { (void)s;(void)k;(void)p;*e=0;return S_OK; }
static HRESULT WINAPI leave(IDropTarget *s) { (void)s;return S_OK; }
static HRESULT WINAPI drop(IDropTarget *s,IDataObject *d,DWORD k,POINTL p,DWORD *e) { return enter(s,d,k,p,e); }
static IDropTargetVtbl vtable={query,addref,release,enter,over,leave,drop};
static void report(const char *label, ULONG_PTR value) {
    char text[180];DWORD written;
    int n=wsprintfA(text,"%s: 0x%Ix\r\n",label,value);
    WriteFile(output,text,n,&written,0); FlushFileBuffers(output);
}
static int contains(const WCHAR *s,const WCHAR *needle) {
    for(;*s;s++){const WCHAR *a=s,*b=needle;while(*a&&*b&&*a==*b){a++;b++;}if(!*b)return 1;}return 0;
}
void mainCRTStartup(void) {
    output=CreateFileW(contains(GetCommandLineW(),L"--child") ? L"C:\\fixture-child.txt" : L"C:\\fixture-parent.txt",GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    HRESULT hr=OleInitialize(0);report("OleInitialize",(ULONG)hr);
    if(FAILED(hr))ExitProcess(2);
    if(contains(GetCommandLineW(),L"--child")) {
        HWND hwnd=FindWindowW(L"STATIC",L"Plugg OLE lifetime fixture");
        DWORD owner=0;GetWindowThreadProcessId(hwnd,&owner);
        report("child pid",GetCurrentProcessId());report("window owner",owner);
        report("foreign property",(ULONG_PTR)GetPropW(hwnd,L"OleDropTargetInterface"));
        hr=RevokeDragDrop(hwnd);report("foreign RevokeDragDrop result",(ULONG)hr);
        OleUninitialize();ExitProcess(FAILED(hr)?0:3);
    }
    HWND hwnd=CreateWindowExW(0,L"STATIC",L"Plugg OLE lifetime fixture",WS_OVERLAPPED,0,0,100,100,0,0,GetModuleHandleW(0),0);
    if(!hwnd)ExitProcess(4);
    IDropTarget *target=VirtualAlloc((void*)0x500000000000ULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!target)ExitProcess(5);
    target->lpVtbl=&vtable;refs=1;
    for(int i=0;i<100;i++) {
        if(FAILED(RegisterDragDrop(hwnd,target))||FAILED(RevokeDragDrop(hwnd))||refs!=1)ExitProcess(6);
    }
    report("normal register/revoke cycles passed",100);
    if(!contains(GetCommandLineW(),L"--foreign")) {
        VirtualFree(target,0,MEM_RELEASE);DestroyWindow(hwnd);OleUninitialize();ExitProcess(0);
    }
    hr=RegisterDragDrop(hwnd,target);report("RegisterDragDrop",(ULONG)hr);
    if(FAILED(hr))ExitProcess(7);
    WCHAR exe[1024],cmd[1100];GetModuleFileNameW(0,exe,1024);wsprintfW(cmd,L"\"%s\" --child",exe);
    STARTUPINFOW si={0};PROCESS_INFORMATION pi={0};si.cb=sizeof(si);
    si.dwFlags=STARTF_USESTDHANDLES;si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    if(!CreateProcessW(0,cmd,0,0,TRUE,0,0,0,&si,&pi))ExitProcess(8);
    DWORD start=GetTickCount(),code;
    while(WaitForSingleObject(pi.hProcess,0)==WAIT_TIMEOUT) {
        MSG msg;while(PeekMessageW(&msg,0,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
        if(GetTickCount()-start>15000){TerminateProcess(pi.hProcess,9);break;}
        Sleep(10);
    }
    GetExitCodeProcess(pi.hProcess,&code);report("child exit",code);
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
    hr=RevokeDragDrop(hwnd);report("owner RevokeDragDrop",(ULONG)hr);
    report("remaining refs",refs);DestroyWindow(hwnd);VirtualFree(target,0,MEM_RELEASE);OleUninitialize();ExitProcess(code?10:0);
}
