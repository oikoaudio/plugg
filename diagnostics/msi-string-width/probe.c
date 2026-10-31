/* Own-code probe for Wine saving an MSI with mixed string reference widths.
 *
 * The first session writes a database of about 61,000 strings, which fits in
 * 2-byte references, and a table called Other. The second session opens only
 * Big and adds more strings, so the pool grows past 0xffff entries. Wine then
 * switches the file to 3-byte references, and an unpatched Wine saves only the
 * tables it has open. The third session reads Other back. Unpatched, the query
 * fails, because the file's table list can no longer be read. The result goes
 * to C:\msi-width-probe.txt, and a run that ends early says where it stopped.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */
#include <stdio.h>
#include <windows.h>
#include <msi.h>
#include <msiquery.h>

#define DATABASE "C:\\msi-width-probe.msi"
#define FIRST 61000
#define SECOND 1000

static FILE *output;

static int stop(const char *step, UINT result) {
    fprintf(output, "%s: FAILED %u\r\n", step, result);
    fclose(output);
    return 1;
}

static UINT sql(MSIHANDLE database, const char *query) {
    MSIHANDLE view;
    UINT result = MsiDatabaseOpenViewA(database, query, &view);
    if (result) return result;
    result = MsiViewExecute(view, 0);
    MsiViewClose(view);
    MsiCloseHandle(view);
    return result;
}

static UINT add_strings(MSIHANDLE database, int first, int count) {
    MSIHANDLE view, record = MsiCreateRecord(1);
    char value[32];
    UINT result = MsiDatabaseOpenViewA(database, "INSERT INTO `Big` (`Key`) VALUES (?)", &view);
    if (result) return result;
    for (int i = first; i < first + count && !result; i++) {
        snprintf(value, sizeof value, "string %d", i);
        MsiRecordSetStringA(record, 1, value);
        result = MsiViewExecute(view, record);
    }
    MsiViewClose(view);
    MsiCloseHandle(view);
    MsiCloseHandle(record);
    return result;
}

int main(void) {
    MSIHANDLE database, view, record;
    char value[32];
    DWORD size = sizeof value;
    UINT result;

    output = fopen("C:\\msi-width-probe.txt", "wb");
    DeleteFileA(DATABASE);

    if ((result = MsiOpenDatabaseA(DATABASE, MSIDBOPEN_CREATE, &database))) return stop("create", result);
    if ((result = sql(database, "CREATE TABLE `Big` (`Key` CHAR(32) NOT NULL PRIMARY KEY `Key`)"))) return stop("create Big", result);
    if ((result = sql(database, "CREATE TABLE `Other` (`Key` CHAR(32) NOT NULL PRIMARY KEY `Key`)"))) return stop("create Other", result);
    if ((result = sql(database, "INSERT INTO `Other` (`Key`) VALUES ('untouched')"))) return stop("fill Other", result);
    if ((result = add_strings(database, 0, FIRST))) return stop("fill Big", result);
    if ((result = MsiDatabaseCommit(database))) return stop("first commit", result);
    MsiCloseHandle(database);

    if ((result = MsiOpenDatabaseA(DATABASE, MSIDBOPEN_TRANSACT, &database))) return stop("reopen", result);
    if ((result = add_strings(database, FIRST, SECOND))) return stop("grow Big", result);
    if ((result = MsiDatabaseCommit(database))) return stop("second commit", result);
    MsiCloseHandle(database);
    fprintf(output, "grew the string pool\r\n");

    if ((result = MsiOpenDatabaseA(DATABASE, MSIDBOPEN_READONLY, &database))) return stop("read Other: open", result);
    if ((result = MsiDatabaseOpenViewA(database, "SELECT `Key` FROM `Other`", &view))) return stop("read Other: query", result);
    if ((result = MsiViewExecute(view, 0))) return stop("read Other: execute", result);
    if ((result = MsiViewFetch(view, &record))) return stop("read Other: fetch", result);
    if ((result = MsiRecordGetStringA(record, 1, value, &size))) return stop("read Other: value", result);
    fprintf(output, "read Other: %s\r\n", value);
    fclose(output);
    return 0;
}
