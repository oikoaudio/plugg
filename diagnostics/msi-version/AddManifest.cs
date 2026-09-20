// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Runtime.InteropServices;
class AddManifest {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr BeginUpdateResource(string path,bool delete);
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateResource(IntPtr handle,IntPtr type,IntPtr name,ushort language,byte[] data,uint size);
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool EndUpdateResource(IntPtr handle,bool discard);
 static void Main(string[] args) {
  byte[] data=File.ReadAllBytes(args[1]); var h=BeginUpdateResource(args[0],false);
  if(h==IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
  if(!UpdateResource(h,(IntPtr)24,(IntPtr)1,0,data,(uint)data.Length)) { EndUpdateResource(h,true); throw new System.ComponentModel.Win32Exception(); }
  if(!EndUpdateResource(h,false)) throw new System.ComponentModel.Win32Exception();
 }
}
