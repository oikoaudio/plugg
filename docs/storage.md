# How much disk this needs, and what it is spent on

Windows plug-ins on Linux take more disk than Windows plug-ins on Windows. Not much more, and for reasons you can list, but the first folder listing can still be a shock. This page breaks the number down.

All figures come from a real library with five vendors and 38 published plug-ins, measured in September 2026.

## The short answer

**About 1.5 GB once, then roughly what each vendor's products would take on Windows, plus about 650 MB per vendor.**

A library with five vendors came to 20 GB. Two of those vendors used 13 GB of it, and would have used nearly the same on Windows.

## Where it goes

### Paid once, however many vendors you add

| Size | What |
| --- | --- |
| ~1.4 GB | The Proton runtime. One copy, shared by every environment. |
| ~120 MB | Downloaded components, kept so a second setup does not fetch them again. |

### Per vendor

Each vendor gets its own environment, a private Windows for its installer to install into. One vendor's components therefore cannot break another's. That isolation is why a vendor keeps working once it works at all, and it costs disk.

| Size | What |
| --- | --- |
| ~650 MB | The Windows skeleton inside the environment. Nearly identical between environments. |
| varies | Whatever the vendor installs. |

The second line is the one that matters, and it varies a lot:

| Vendor | Total | Skeleton | What the vendor installed |
| --- | --- | --- | --- |
| Four free plug-ins | 750 MB | 663 MB | 49 MB |
| 24 plug-ins from one vendor | 1.2 GB | 644 MB | 550 MB |
| Two plug-ins, via a helper app | 2.1 GB | 640 MB | 1.4 GB, nearly all of it the vendor's own helper application |
| Five instruments, with content | 5.9 GB | ~650 MB | 5.2 GB, of which 1.7 GB is sample content |
| Three plug-ins, licensed through iLok | 7.4 GB | ~650 MB | 6.7 GB, including 2.2 GB of Microsoft .NET and 1.9 GB of PACE licensing components |

So "a vendor costs 7 GB" is misleading. That vendor's *products* cost 7 GB. They would cost about the same in a Windows installation, because .NET, PACE and sample libraries are that size wherever they live.

### Kept alongside

| Size | What |
| --- | --- |
| ~1 GB | A copy of each installer you added, kept beside its installation. |

This one is easy to miss. It is invisible, and it duplicates files you already have in your downloads folder. A 300 MB installer stays 300 MB forever. Deleting an installation or discarding a failed attempt also deletes its copy.

## What you can do about it

**Install fewer, larger vendors rather than many small ones.** The 650 MB skeleton is per environment, so ten vendors with one plug-in each cost more in overhead than one vendor with fifty. Plug-ins that can share an environment already do. You can merge two that ended up apart, but the interface does not offer this yet. Doing it by hand means moving publications, prefixes and licensing records together.

**Point vendor content at a shared location.** Several instrument vendors let you choose where sample content lives. Content outside the environment is stored once, however many environments exist. For a large instrument library it outweighs everything else on this page.

**Delete what you tried and did not keep.** The Environments view lists everything on disk with its size, and separates environments that publish plug-ins from those that do not. A failed experiment is usually the biggest single thing you can remove.

**Do not delete environments that hold activations** until you have deactivated in the vendor's own manager. The app asks you to type a phrase before it deletes one. That phrase is the warning, not a formality.

## What the app does for you

- A failed setup that never got as far as installing anything removes its own environment, so a bad download does not leave a few gigabytes behind.
- Environments share runtimes. The app offers to reclaim a runtime that no environment uses any more, and downloads it again if it is needed later.
- Plug-ins that can share an environment do. Four plug-ins from one vendor are one environment, not four.

## What it does not do yet

- **The Windows skeleton is copied, not shared.** On a copy-on-write filesystem (btrfs, XFS, ZFS), Plugg could create it from a clean template at almost no cost, and environments would only diverge where they differ. That would save about 18% of a library this size, and more for someone with many small vendors. It is not implemented.
- **Microsoft runtimes are per environment.** Two vendors that both need .NET 4.8 pay for it twice. Sharing it is hard, because .NET installs into the environment's registry and cannot simply live in a shared directory. After the skeleton, it is the largest duplicated item.
- **Plugg never reclaims installer copies on its own**, and the interface does not show them.
