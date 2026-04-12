# set_wallpaper_helper.ps1
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File set_wallpaper_helper.ps1 <desktop-guid> <wallpaper-path>
param(
    [string]$DesktopGuid,
    [string]$WallpaperPath
)

if (-not $DesktopGuid -or -not $WallpaperPath) {
    Write-Error "Usage: set_wallpaper_helper.ps1 <desktop-guid> <wallpaper-path>"
    exit 1
}

$code = @'
using System;
using System.Runtime.InteropServices;

public static class WallpaperSetter
{
    // ── IVirtualDesktop (opaque) ───────────────────────────────────────────
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("536D3495-B208-4CC9-AE26-DE8111275BF8")]
    public interface IVirtualDesktop { }

    // ── IServiceProvider ──────────────────────────────────────────────────
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("6D5140C1-7436-11CE-8034-00AA006009FA")]
    public interface IServiceProvider {
        [PreserveSig]
        int QueryService(ref Guid guidService, ref Guid riid,
                         [MarshalAs(UnmanagedType.Interface)] out object ppvObject);
    }

    // ── ImmersiveShell CoClass ─────────────────────────────────────────────
    [ComImport, Guid("C2F03A33-21F5-47FA-B4BB-156362A2F239"),
     ClassInterface(ClassInterfaceType.None)]
    public class ImmersiveShell { }

    // ── Win11 22H2 layout (GUID 1841C6D7) ─────────────────────────────────
    // FindDesktop @ 13 (vtable index), SetDesktopWallpaper @ 16
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("1841C6D7-4F9D-42C0-AF41-8747538F10E5")]
    public interface IVdMgrInternal_22H2 {
        int GetCount(IntPtr hMon);                                        // 3
        void Pad04(object a, object b);                                   // 4
        bool Pad05(object a);                                             // 5
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop GetCurrentDesktop(IntPtr hMon);                   // 6
        void Pad07(IntPtr hMon, out object arr);                          // 7
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop Pad08(IVirtualDesktop d, int dir);                // 8
        void Pad09(IntPtr hMon, IVirtualDesktop d);                       // 9
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop Pad10(IntPtr hMon);                               // 10
        void Pad11(IVirtualDesktop d, IntPtr hMon, int n);                // 11
        void Pad12(IVirtualDesktop d, IVirtualDesktop f);                 // 12
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop FindDesktop(ref Guid id);                         // 13
        void Pad14(IVirtualDesktop d, out object a, out object b);        // 14
        void Pad15(IVirtualDesktop d,
                   [MarshalAs(UnmanagedType.HString)] string name);       // 15
        void SetDesktopWallpaper(
            IVirtualDesktop d,
            [MarshalAs(UnmanagedType.LPWStr)] string path);               // 16
    }

    // ── Win11 24H2 layout (GUID 53F5CA0B) ─────────────────────────────────
    // FindDesktop @ 15, SetDesktopWallpaper @ 18
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown),
     Guid("53F5CA0B-158F-4124-900C-057158060B27")]
    public interface IVdMgrInternal_24H2 {
        int GetCount(IntPtr hMon);                                        // 3
        void Pad04(object a, object b);                                   // 4
        bool Pad05(object a);                                             // 5
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop GetCurrentDesktop(IntPtr hMon);                   // 6
        void Pad07(out object arr);                                       // 7
        void Pad08(IntPtr hMon, out object arr);                          // 8
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop Pad09(IntPtr hMon);                               // 9
        void Pad10(IntPtr hMon, IVirtualDesktop d);                       // 10
        void Pad11(IntPtr hMon, IVirtualDesktop d);                       // 11
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop Pad12(IntPtr hMon);                               // 12
        void Pad13(IVirtualDesktop d, IntPtr hMon, int n);                // 13
        void Pad14(IVirtualDesktop d, IVirtualDesktop f);                 // 14
        [return:MarshalAs(UnmanagedType.Interface)]
        IVirtualDesktop FindDesktop(ref Guid id);                         // 15
        void Pad16(IVirtualDesktop d, out object a, out object b);        // 16
        void Pad17(IVirtualDesktop d,
                   [MarshalAs(UnmanagedType.HString)] string name);       // 17
        void SetDesktopWallpaper(
            IVirtualDesktop d,
            [MarshalAs(UnmanagedType.LPWStr)] string path);               // 18
    }

    public static int Run(string guidStr, string wallpaperPath)
    {
        Guid desktopGuid;
        try { desktopGuid = new Guid(guidStr); }
        catch { Console.Error.WriteLine("Invalid GUID: " + guidStr); return 2; }

        object shellObj = new ImmersiveShell();
        IServiceProvider sp = (IServiceProvider)shellObj;

        Guid g22 = new Guid("1841C6D7-4F9D-42C0-AF41-8747538F10E5");
        Guid g24 = new Guid("53F5CA0B-158F-4124-900C-057158060B27");

        // Try 22H2 layout
        object mgrObj22 = null;
        int hr = sp.QueryService(ref g22, ref g22, out mgrObj22);
        if (hr == 0 && mgrObj22 != null) {
            try {
                var mgr = (IVdMgrInternal_22H2)mgrObj22;
                var desktop = mgr.FindDesktop(ref desktopGuid);
                if (desktop != null) {
                    mgr.SetDesktopWallpaper(desktop, wallpaperPath);
                    Console.WriteLine("OK (22H2 layout) " + guidStr);
                    return 0;
                }
                Console.Error.WriteLine("FindDesktop(22H2) returned null");
            } catch (Exception ex) {
                Console.Error.WriteLine("22H2 attempt failed: " + ex.Message);
            }
        }

        // Try 24H2 layout
        object mgrObj24 = null;
        hr = sp.QueryService(ref g24, ref g24, out mgrObj24);
        if (hr == 0 && mgrObj24 != null) {
            try {
                var mgr = (IVdMgrInternal_24H2)mgrObj24;
                var desktop = mgr.FindDesktop(ref desktopGuid);
                if (desktop != null) {
                    mgr.SetDesktopWallpaper(desktop, wallpaperPath);
                    Console.WriteLine("OK (24H2 layout) " + guidStr);
                    return 0;
                }
                Console.Error.WriteLine("FindDesktop(24H2) returned null");
            } catch (Exception ex) {
                Console.Error.WriteLine("24H2 attempt failed: " + ex.Message);
            }
        }

        Console.Error.WriteLine("All attempts failed for " + guidStr);
        return 1;
    }
}
'@

try {
    Add-Type -TypeDefinition $code -ErrorAction Stop
} catch {
    Write-Error "Compile error: $_"
    exit 1
}

$result = [WallpaperSetter]::Run($DesktopGuid, $WallpaperPath)
exit $result
