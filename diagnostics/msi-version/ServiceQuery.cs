// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Runtime.InteropServices;
class ServiceQuery {
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr OpenSCManager(string machine,string database,uint access);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr OpenService(IntPtr manager,string name,uint access);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool QueryServiceConfig2(IntPtr service,uint level,IntPtr buffer,uint size,out uint needed);
 [DllImport("advapi32.dll")] static extern bool CloseServiceHandle(IntPtr handle);
 static void Main() {
  var manager=OpenSCManager(null,null,1);
  if(manager==IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
  try {
   var service=OpenService(manager,"RpcSs",1);
   if(service==IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
   try {
    foreach(uint level in new uint[]{1,2,3}) {
     uint needed; bool ok=QueryServiceConfig2(service,level,IntPtr.Zero,0,out needed);
     int error=Marshal.GetLastWin32Error();
     Console.WriteLine("level={0} success={1} error={2} bytes={3}",level,ok,error,needed);
    }
   } finally { CloseServiceHandle(service); }
  } finally { CloseServiceHandle(manager); }
 }
}
