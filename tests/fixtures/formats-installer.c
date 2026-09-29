/* SPDX-License-Identifier: GPL-3.0-or-later
 * A real Windows PE installer that installs the test gain as VST3, VST2 and
 * CLAP, each where vendors commonly put that format. */
typedef unsigned short wchar;
typedef unsigned long DWORD;
typedef void* HANDLE;
__declspec(dllimport) DWORD GetEnvironmentVariableW(const wchar*,wchar*,DWORD);
__declspec(dllimport) int CreateDirectoryW(const wchar*,void*);
__declspec(dllimport) HANDLE CreateFileW(const wchar*,DWORD,DWORD,void*,DWORD,DWORD,HANDLE);
__declspec(dllimport) int WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
__declspec(dllimport) int CloseHandle(HANDLE);
__declspec(dllimport) void ExitProcess(unsigned);
#include "plugin-blob.h"
#include "vst2-blob.h"
#include "clap-blob.h"
static void append(wchar* dst,const wchar* src){while(*dst)++dst;while((*dst++=*src++)) {}}
static void install(const wchar* const* folders,const wchar* name,const unsigned char* blob,DWORD size){
 wchar path[512];
 if(!GetEnvironmentVariableW((const wchar*)L"ProgramFiles",path,400))ExitProcess(1);
 for(;*folders;++folders){append(path,*folders);CreateDirectoryW(path,0);}
 append(path,name);
 HANDLE out=CreateFileW(path,0x40000000,0,0,2,0x80,0);
 if(out==(HANDLE)(long long)-1)ExitProcess(2);
 DWORD written=0;
 int ok=WriteFile(out,blob,size,&written,0);
 CloseHandle(out);
 if(!ok||written!=size)ExitProcess(3);
}
void mainCRTStartup(void){
 static const wchar* const vst3[]={(const wchar*)L"\\Common Files",(const wchar*)L"\\VST3",0};
 static const wchar* const vst2[]={(const wchar*)L"\\VSTPlugins",0};
 static const wchar* const clap[]={(const wchar*)L"\\Common Files",(const wchar*)L"\\CLAP",0};
 install(vst3,(const wchar*)L"\\Plugg Test Gain.vst3",plugin_blob,(DWORD)sizeof(plugin_blob));
 install(vst2,(const wchar*)L"\\Plugg Test Gain 2.dll",vst2_blob,(DWORD)sizeof(vst2_blob));
 install(clap,(const wchar*)L"\\Plugg Test Gain.clap",clap_blob,(DWORD)sizeof(clap_blob));
 ExitProcess(0);
}
