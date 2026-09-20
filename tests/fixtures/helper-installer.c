/* SPDX-License-Identifier: GPL-3.0-or-later
 * A real Windows PE installer for the deterministic test plug-in. */
typedef unsigned short wchar;
typedef unsigned long DWORD;
typedef void* HANDLE;
__declspec(dllimport) DWORD GetEnvironmentVariableW(const wchar*,wchar*,DWORD);
__declspec(dllimport) int CreateDirectoryW(const wchar*,void*);
__declspec(dllimport) HANDLE CreateFileW(const wchar*,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
__declspec(dllimport) int WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
__declspec(dllimport) int CloseHandle(HANDLE);
__declspec(dllimport) void ExitProcess(unsigned);
__declspec(dllimport) DWORD GetModuleFileNameW(HANDLE,wchar*,DWORD);
__declspec(dllimport) int CopyFileW(const wchar*,const wchar*,int);
__declspec(dllimport) const wchar* GetCommandLineW(void);
#include "plugin-blob.h"
static void append(wchar* dst,const wchar* src){while(*dst)++dst;while((*dst++=*src++)) {}}
void mainCRTStartup(void){
 const wchar* command=GetCommandLineW();
 int install=0;
 for(;*command;++command){
  if(command[0]=='-' && command[1]=='-' && command[2]=='i') {install=1;break;}
 }
 if(!install)ExitProcess(0); /* Installed helper opens and exits without login. */
 wchar own[512],helper[512];
 if(!GetModuleFileNameW(0,own,512))ExitProcess(4);
 if(!GetEnvironmentVariableW((const wchar*)L"ProgramFiles",helper,400))ExitProcess(5);
 append(helper,(const wchar*)L"\\Plugg Fixture");CreateDirectoryW(helper,0);
 append(helper,(const wchar*)L"\\Helper.exe");
 if(!CopyFileW(own,helper,0))ExitProcess(6);
 wchar path[512];
 if(!GetEnvironmentVariableW((const wchar*)L"ProgramFiles",path,400))ExitProcess(1);
 append(path,(const wchar*)L"\\Common Files");CreateDirectoryW(path,0);
 append(path,(const wchar*)L"\\VST3");CreateDirectoryW(path,0);
 append(path,(const wchar*)L"\\Plugg Test Gain.vst3");
 HANDLE out=CreateFileW(path,0x40000000,0,0,2,0x80,0);
 if(out==(HANDLE)(long long)-1)ExitProcess(2);
 DWORD written=0;
 int ok=WriteFile(out,plugin_blob,(DWORD)sizeof(plugin_blob),&written,0);
 CloseHandle(out);
 ExitProcess(ok&&written==sizeof(plugin_blob)?0:3);
}
