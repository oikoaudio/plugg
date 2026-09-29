# Notes for Cabinet

[Cabinet](https://github.com/Mark12870/cabinet) is a Flatpak with the same design as Plugg: one prefix per vendor, a patched yabridge, and one session per prefix. It is GPL-3.0-or-later, as Plugg is. These are two issues worth opening there, drafted for review. Neither has been posted.

## Every prefix looks like a different computer

Wine gives every new prefix a random `MachineGuid` (`HKLM\Software\Microsoft\Cryptography`). Cabinet creates one prefix per vendor and does not set it, so a vendor that identifies machines by `MachineGuid` sees each of those prefixes as a separate computer. A vendor with a limit of three machines could lose all three to prefixes on one computer. Recreating a prefix also gives it a new random value.

Plugg derives one value per computer by hashing the host's `/etc/machine-id`, and writes it into every new prefix through Wine's own registry tool before any vendor software runs. The result is the same for every prefix on the computer and survives reinstalls, and the Windows side never sees the host's own identifier. `docs/licensing-safety.md`, section "One computer, one machine", describes it.

## What iLok would need

Cabinet's library has no iLok or PACE entry. From Plugg's work on it:

1. PACE's unmodified installer fails on stock Wine for two reasons. `rundll32.exe` reports Windows 6.2 to the DLLs it loads, and `services.exe` does not store service failure actions. Plugg's runtime has fixes for both (`docs/upstream/wine-patches.md`). Cabinet's runners are stock builds, so it would need a runner with those fixes, or the fixes upstream.
2. Every iLok vendor shares one PACE installation, which iLok counts as one computer. That means one shared prefix for all iLok products, not one per vendor.
3. That prefix needs a stable machine identity. See the issue above.
4. PACE runs a Windows service. Cabinet's sessions end ten seconds after the last job, which stops every service. Nobody has tested how PACE handles restarting that often.
5. Activations are bound to the prefix. `flatpak uninstall --delete-data` deletes it, and with it any activation that was not deactivated first. The iLok prefix probably belongs outside the app's data directory, or behind an explicit warning.

Plugg has not tested PACE on Wine 11, which Cabinet's newest runners use.
