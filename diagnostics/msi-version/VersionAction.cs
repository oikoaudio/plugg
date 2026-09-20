// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Deployment.WindowsInstaller;
public class VersionAction {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct VersionInfo {
        public uint size, major, minor, build, platform;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string servicePack;
    }
    [DllImport("ntdll.dll", CharSet=CharSet.Unicode)]
    static extern int RtlGetVersion(ref VersionInfo version);
    [CustomAction]
    public static ActionResult Report(Session session) {
        var v = new VersionInfo(); v.size = (uint)Marshal.SizeOf(v);
        var status = RtlGetVersion(ref v);
        session.Log("PLUGG_PROBE managed={0} native={1}.{2}.{3} status={4} host={5} bits={6}",
            Environment.OSVersion.Version, v.major, v.minor, v.build, status,
            Process.GetCurrentProcess().MainModule.FileName, IntPtr.Size * 8);
        // End before installation: this package deliberately installs nothing.
        return ActionResult.Failure;
    }
}
