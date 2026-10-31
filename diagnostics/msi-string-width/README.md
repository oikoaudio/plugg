# Wine damages a large MSI when it saves one

Kontakt 8 8.14.1 did not install under UMU-Proton 10.0-4, and neither the installer nor Native Access noticed. The installer ran for about 75 seconds and exited normally. Native Access reported success and offered **Install** again. No Kontakt 8 file existed.

## What happens

Kontakt 8's InstallAware setup opens its MSI, edits it and commits it, then calls `MsiInstallProductA`. With `WINEDEBUG=+msi`, that call opens the package and gives up before it runs a single action. Every property read after that is "not found", because the engine cannot read its own temporary table:

```
trace:msi:MSI_DatabaseOpenViewW L"SELECT `Value` FROM `_Property` WHERE `_Property`=?"
trace:msi:MSI_ParseSQL Parse returned 1
trace:msi:msi_get_property property L"PackageCode" not found
```

`Parse returned 1` means Wine could not load a table. `msiinfo` shows why, and prints the same message as Wine, `Table size is invalid 148/3`. The tables and the string pool use different widths:

| | Original MSI | After the edit |
| --- | --- | --- |
| String pool entries | 57,160 | 85,741 |
| String references | 2 bytes | 3 bytes |
| `!_Columns` | 3,008 bytes | 3,760 bytes, re-saved |
| `!_Tables` | 148 bytes | 148 bytes, not re-saved |

## Why

An MSI stores references to its strings in 2 or 3 bytes, and every table must use the same width. `msi_save_string_table()` chooses the width from `st->maxcount`, and `MSI_CommitTables()` then saves only the tables in `db->tables`. Tables nobody has opened stay in the file with the old width.

`maxcount` is the capacity of the pool, not the number of strings. It grows by half each time: 57,161 + 1 + 28,580 is 85,742. So a database of about 43,700 strings crosses 0xffff when it gains one string, and it does not need to hold 65,535 strings for this to happen.

The damage starts at the first commit. The trace shows the installer changing 11,820 rows of `Component`, but that table has 16,745 rows. Its 200,940 bytes read as 11,820 rows of 17 bytes once the pool declares 3-byte references, so the installer was changing misread rows.

## The fix

[The patch](../../patches/wine/0004-msi-Rewrite-every-table-when-the-string-reference-wi.patch) loads the remaining tables while they can still be read with the old width, so that every table is saved with the new one, and then records the new width. It is in the `plugg-2` runtime and not yet in upstream Wine.

## The probe

`probe.c` needs no vendor software. It writes a database of 61,000 strings and a table called `Other`, reopens it and adds strings to one table until the pool grows, then reads `Other` back. On stock UMU-Proton 10.0-4 that read fails. With the patch, the 32-bit and 64-bit builds both return the row.

```sh
sh diagnostics/msi-string-width/build.sh
python3 scripts/test-runtime-patches.py --library <a test library>
```
