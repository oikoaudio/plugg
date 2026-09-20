/* SPDX-License-Identifier: GPL-3.0-or-later
 * Read-only OLE window/property inventory. Does not dereference drop targets. */
#include <windows.h>
static HANDLE output;
static BOOL CALLBACK inspect(HWND hwnd, LPARAM unused) {
    (void)unused;
    HANDLE target=GetPropW(hwnd,L"OleDropTargetInterface");
    if(!target)return TRUE;
    DWORD pid=0,written,length=1024;
    GetWindowThreadProcessId(hwnd,&pid);
    char image[1024],line[1300];image[0]=0;
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    if(process){QueryFullProcessImageNameA(process,0,image,&length);CloseHandle(process);}
    int n=wsprintfA(line,"hwnd=0x%Ix owner=%lu target=0x%Ix image=%s\r\n",(ULONG_PTR)hwnd,pid,(ULONG_PTR)target,image);
    WriteFile(output,line,n,&written,0);return TRUE;
}
static BOOL CALLBACK top(HWND hwnd,LPARAM unused) {
    inspect(hwnd,unused);EnumChildWindows(hwnd,inspect,0);return TRUE;
}
void mainCRTStartup(void) {
    output=CreateFileW(L"C:\\Plugg\\drop-owners.txt",GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    if(output==INVALID_HANDLE_VALUE)ExitProcess(1);
    EnumWindows(top,0);CloseHandle(output);ExitProcess(0);
}
