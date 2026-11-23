/* envxx shim: launch a stored tool, preserving every argument exactly.
 *
 * A .bat wrapper cannot do this. cmd.exe expands "%*" by re-parsing the
 * caller's text, so an argument containing a space arrives split in two;
 * quoted paths break. This program receives already-parsed argv and rebuilds
 * a command line using the same rules CommandLineToArgvW parses with, so the
 * child sees exactly what the caller meant.
 *
 * The target path travels inside this file: the generator appends a marker
 * and the path after the PE image, which Windows ignores. The path is
 * relative to this executable, so moving the whole envxx store keeps the
 * shim working.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define MARKER L"\n@@ENVXX-TARGET@@"
#define TRAILER_MAX 16384

static void die(const wchar_t *what) {
    fwprintf(stderr, L"envxx shim: %ls (error %lu)\n", what, GetLastError());
    ExitProcess(127);
}

/* Append one argument, escaped the way CommandLineToArgvW will undo it:
 * backslashes are doubled only when they precede a quote, and a quote
 * carries one extra backslash. */
static void append_arg(wchar_t *out, const wchar_t *arg, int first) {
    if (!first) *out++ = L' ';

    int needs_quotes = (*arg == L'\0');
    for (const wchar_t *p = arg; *p; p++) {
        if (*p == L' ' || *p == L'\t' || *p == L'"') {
            needs_quotes = 1;
            break;
        }
    }
    if (!needs_quotes) {
        wcscpy(out, arg);
        return;
    }

    *out++ = L'"';
    for (const wchar_t *p = arg;; p++) {
        size_t slashes = 0;
        while (*p == L'\\') {
            slashes++;
            p++;
        }
        if (*p == L'\0') {
            for (size_t i = 0; i < slashes * 2; i++) *out++ = L'\\';
            break;
        }
        if (*p == L'"') {
            for (size_t i = 0; i < slashes * 2 + 1; i++) *out++ = L'\\';
            *out++ = L'"';
        } else {
            for (size_t i = 0; i < slashes; i++) *out++ = L'\\';
            *out++ = *p;
        }
    }
    *out++ = L'"';
    *out = L'\0';
}

/* Read the target path that the generator appended to this file.
 *
 * The trailer is UTF-8 bytes after the PE image, which may not start on a
 * wchar_t boundary, so it is located as bytes and converted once found.
 */
static int read_target(wchar_t *out, size_t cap) {
    wchar_t self[MAX_PATH * 4];
    if (!GetModuleFileNameW(NULL, self, MAX_PATH * 4)) return 0;

    HANDLE file = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;

    LARGE_INTEGER size;
    if (!GetFileSizeEx(file, &size)) {
        CloseHandle(file);
        return 0;
    }

    DWORD want = size.QuadPart < TRAILER_MAX ? (DWORD)size.QuadPart : TRAILER_MAX;
    char buffer[TRAILER_MAX + 1];
    LARGE_INTEGER start;
    start.QuadPart = size.QuadPart - want;
    if (!SetFilePointerEx(file, start, NULL, FILE_BEGIN)) {
        CloseHandle(file);
        return 0;
    }
    DWORD got = 0;
    if (!ReadFile(file, buffer, want, &got, NULL)) {
        CloseHandle(file);
        return 0;
    }
    CloseHandle(file);
    buffer[got] = '\0';

    /* The trailer follows padding that is mostly NUL bytes, and strstr stops
     * at the first NUL, so the search has to run over an explicit length. */
    static const char needle[] = "@@ENVXX-TARGET@@";
    const size_t needle_len = sizeof(needle) - 1;
    char *marker = NULL;
    for (DWORD i = 0; i + needle_len <= got; i++) {
        if (buffer[i] == '@' && memcmp(buffer + i, needle, needle_len) == 0) {
            marker = buffer + i;
            break;
        }
    }
    if (!marker) return 0;
    marker += needle_len;

    /* the path runs to the newline the generator wrote after it */
    char *end = memchr(marker, '\n', (size_t)(buffer + got - marker));
    size_t length = end ? (size_t)(end - marker) : (size_t)(buffer + got - marker);
    if (length == 0) return 0;

    int wide = MultiByteToWideChar(CP_UTF8, 0, marker, (int)length, out, (int)cap - 1);
    if (wide <= 0) return 0;
    out[wide] = L'\0';
    return 1;
}

int wmain(int argc, wchar_t **argv) {
    wchar_t target[MAX_PATH * 4];
    if (!read_target(target, MAX_PATH * 4)) {
        fwprintf(stderr, L"envxx shim: this file has no target; regenerate it "
                          L"with 'envxx <tool> set_path'\n");
        return 127;
    }

    wchar_t self_dir[MAX_PATH * 4];
    if (!GetModuleFileNameW(NULL, self_dir, MAX_PATH * 4)) die(L"cannot locate itself");
    wchar_t *slash = wcsrchr(self_dir, L'\\');
    if (slash) *slash = L'\0';

    /* The stored target is relative to this executable. Making it absolute
     * here means the child's working directory does not affect which tool
     * runs. */
    wchar_t exe[MAX_PATH * 4];
    if (PathIsRelativeW(target)) {
        swprintf(exe, MAX_PATH * 4, L"%ls\\%ls", self_dir, target);
    } else {
        wcsncpy(exe, target, MAX_PATH * 4 - 1);
        exe[MAX_PATH * 4 - 1] = L'\0';
    }

    /* Command line: "<exe>" arg1 arg2 ...; argv[0] of the child. */
    size_t capacity = (size_t)(MAX_PATH * 8) + (size_t)argc * MAX_PATH;
    wchar_t *cmdline = malloc(capacity * sizeof(wchar_t));
    if (!cmdline) die(L"out of memory");

    wchar_t *cursor = cmdline;
    *cursor++ = L'"';
    wcscpy(cursor, exe);
    cursor += wcslen(exe);
    *cursor++ = L'"';

    /* append_arg expects to write at cursor and leaves a NUL behind, so the
     * cursor advances by the length it produced each time */
    for (int i = 1; i < argc; i++) {
        append_arg(cursor, argv[i], 0);
        cursor += wcslen(cursor);
    }

    STARTUPINFOW startup;
    PROCESS_INFORMATION info;
    ZeroMemory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    ZeroMemory(&info, sizeof(info));

    if (!CreateProcessW(exe, cmdline, NULL, NULL, TRUE, 0, NULL, NULL,
                        &startup, &info)) {
        fwprintf(stderr, L"envxx shim: cannot run %ls (error %lu)\n", exe,
                 GetLastError());
        free(cmdline);
        return 127;
    }

    WaitForSingleObject(info.hProcess, INFINITE);
    DWORD code = 127;
    GetExitCodeProcess(info.hProcess, &code);
    CloseHandle(info.hProcess);
    CloseHandle(info.hThread);
    free(cmdline);
    return (int)code;
}
