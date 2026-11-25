/* MyWorld 启动器（Windows 原生入口）
 *
 * 为什么用 C 写这一层：
 *   - 用户要的是双击就能跑的 .exe，而不是先开 PowerShell 再敲命令；
 *   - 查找 Python、拼命令行、转发退出码、处理控制台编码这些都属于「进程管理」，
 *     放在 C 里最直接，也不依赖任何 Python 环境；
 *   - 只有这一层是原生的，业务仍然留在 Python 侧，便于快速迭代。
 *
 * 职责：
 *   1. 以自身所在目录为工作目录（保证 myworld\ 与 web\ 能被找到）
 *   2. 按顺序选择解释器：MYWORLD_PYTHON 环境变量 → .venv → PATH 上的 python/py
 *   3. 启动 `python -m myworld <原样参数>`，强制 UTF-8，等待其结束
 *   4. 透传子进程退出码；出错时停下并提示，避免窗口一闪而过
 *   5. 双击启动（挂在交互式控制台上）时自动打开浏览器；脚本/重定向场景保持安静
 *
 * 启动器自己的开关（不转发给 Python）：
 *   --no-open     不要自动打开浏览器
 *   --open        强制打开（默认在交互式控制台下即打开）
 *   --print-args  只打印最终拼好的命令行后退出，用于排查参数与引号问题
 *
 * 构建（任选一条，用的是 UCRT64 mingw-w64）：
 *   gcc -O2 -municode -static -static-libgcc -o MyWorld.exe tools\launcher.c
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <conio.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

#define CMDLINE_CAP 32767
#define PATH_CAP 4096

static HANDLE g_in = INVALID_HANDLE_VALUE;
static HANDLE g_out = INVALID_HANDLE_VALUE;
static HANDLE g_err = INVALID_HANDLE_VALUE;

/* ---------------- 输出：控制台用宽字符，重定向用 UTF-8 ---------------- */

static void write_stream(HANDLE handle, const wchar_t *text)
{
    DWORD mode = 0;
    DWORD written = 0;

    if (handle == INVALID_HANDLE_VALUE || text == NULL) {
        return;
    }

    if (GetFileType(handle) == FILE_TYPE_CHAR && GetConsoleMode(handle, &mode)) {
        WriteConsoleW(handle, text, (DWORD)wcslen(text), &written, NULL);
        return;
    }

    int bytes = WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL);
    if (bytes <= 1) {
        return;
    }
    char *buffer = (char *)malloc((size_t)bytes);
    if (buffer == NULL) {
        return;
    }
    WideCharToMultiByte(CP_UTF8, 0, text, -1, buffer, bytes, NULL, NULL);
    WriteFile(handle, buffer, (DWORD)(bytes - 1), &written, NULL);
    free(buffer);
}

static void complain(const wchar_t *text)
{
    write_stream(g_err, text);
}

/* 出错时停一下，让双击启动的用户能看到原因 */
static void pause_if_console(void)
{
    DWORD mode = 0;

    if (g_in == INVALID_HANDLE_VALUE) {
        return;
    }
    /* stdin 被重定向时不打断脚本 */
    if (GetFileType(g_in) != FILE_TYPE_CHAR || !GetConsoleMode(g_in, &mode)) {
        return;
    }
    write_stream(g_err, L"\n按任意键关闭窗口…");
    FlushConsoleInputBuffer(g_in);
    (void)_getwch();
}

/* stdin/stdout 都挂在真实控制台上，才认为是「人在用」，而不是脚本/重定向 */
static int console_is_interactive(void)
{
    DWORD mode = 0;

    if (g_in == INVALID_HANDLE_VALUE || g_out == INVALID_HANDLE_VALUE) {
        return 0;
    }
    if (GetFileType(g_in) != FILE_TYPE_CHAR || GetFileType(g_out) != FILE_TYPE_CHAR) {
        return 0;
    }
    return GetConsoleMode(g_in, &mode) != 0 && GetConsoleMode(g_out, &mode) != 0;
}

/* ---------------- 子进程控制 ---------------- */

/* 父进程不因 Ctrl+C 退出，留给 Python/uvicorn 自己优雅收尾 */
static BOOL WINAPI on_console_ctrl(DWORD type)
{
    switch (type) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
        return TRUE;
    default:
        return FALSE;
    }
}

/* ---------------- 命令行拼装（按 Windows 规则加引号） ---------------- */

static int append_literal(wchar_t *dst, size_t cap, size_t *used, const wchar_t *text)
{
    size_t need = wcslen(text);
    if (*used + need + 1 > cap) {
        return 0;
    }
    wmemcpy(dst + *used, text, need);
    *used += need;
    dst[*used] = L'\0';
    return 1;
}

static int append_arg(wchar_t *dst, size_t cap, size_t *used, const wchar_t *arg)
{
    size_t need = 3; /* 两个引号 + 结尾零 */
    const wchar_t *p;
    int quote = (*arg == L'\0');

    for (p = arg; *p != L'\0'; ++p) {
        need += (*p == L'\\') ? 2 : 1;
        if (*p == L' ' || *p == L'\t' || *p == L'"') {
            quote = 1;
        }
    }
    if (*used + need > cap) {
        return 0;
    }

    if (!quote) {
        return append_literal(dst, cap, used, arg);
    }

    dst[(*used)++] = L'"';
    size_t slashes = 0;
    for (p = arg; *p != L'\0'; ++p) {
        if (*p == L'\\') {
            ++slashes;
            continue;
        }
        if (*p == L'"') {
            /* 引号前的反斜杠要加倍，再补一个转义引号 */
            for (size_t i = 0; i < slashes * 2 + 1; ++i) {
                dst[(*used)++] = L'\\';
            }
            dst[(*used)++] = L'"';
            slashes = 0;
            continue;
        }
        for (size_t i = 0; i < slashes; ++i) {
            dst[(*used)++] = L'\\';
        }
        slashes = 0;
        dst[(*used)++] = *p;
    }
    /* 结尾的反斜杠会与收尾引号混淆，同样加倍 */
    for (size_t i = 0; i < slashes * 2; ++i) {
        dst[(*used)++] = L'\\';
    }
    dst[(*used)++] = L'"';
    dst[*used] = L'\0';
    return 1;
}

/* ---------------- 解释器查找 ---------------- */

static int file_exists(const wchar_t *path)
{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

static int copy_path(wchar_t *dst, DWORD cap, const wchar_t *src)
{
    size_t need = wcslen(src);
    if (need + 1 > cap) {
        return 0;
    }
    wmemcpy(dst, src, need + 1);
    return 1;
}

static int find_in_path(const wchar_t *name, wchar_t *out, DWORD cap)
{
    DWORD result = SearchPathW(NULL, name, L".exe", cap, out, NULL);
    return result > 0 && result < cap;
}

/* 返回 1 表示找到；*is_py_launcher 为 1 时表示要用 `py -3` */
static int resolve_python(const wchar_t *exe_dir, wchar_t *out, DWORD cap, int *is_py_launcher)
{
    const wchar_t *override_path = _wgetenv(L"MYWORLD_PYTHON");
    wchar_t venv[MAX_PATH];

    *is_py_launcher = 0;

    if (override_path != NULL && *override_path != L'\0') {
        if (!file_exists(override_path)) {
            return 0; /* 用户显式指定却不存在：直接失败，避免静默换用别的解释器 */
        }
        return copy_path(out, cap, override_path);
    }

    /* 项目内虚拟环境优先 */
    swprintf(venv, MAX_PATH, L"%ls\\.venv\\Scripts\\python.exe", exe_dir);
    if (file_exists(venv)) {
        return copy_path(out, cap, venv);
    }

    if (find_in_path(L"python.exe", out, cap)) {
        return 1;
    }
    if (find_in_path(L"python3.exe", out, cap)) {
        return 1;
    }
    if (find_in_path(L"py.exe", out, cap)) {
        *is_py_launcher = 1;
        return 1;
    }
    return 0;
}

/* ---------------- 主流程 ---------------- */

static int report_missing_runtime(void)
{
    complain(
        L"[MyWorld] 没有找到 Python 解释器。\n"
        L"        请安装 Python 3.10+ 并加入 PATH，\n"
        L"        或在项目内创建 .venv，\n"
        L"        或设置环境变量 MYWORLD_PYTHON 指向 python.exe。\n");
    return 4;
}

int wmain(int argc, wchar_t **argv)
{
    g_in = GetStdHandle(STD_INPUT_HANDLE);
    g_out = GetStdHandle(STD_OUTPUT_HANDLE);
    g_err = GetStdHandle(STD_ERROR_HANDLE);

    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    SetConsoleCtrlHandler(on_console_ctrl, TRUE);

    /* 1. 自身所在目录 */
    wchar_t exe_path[MAX_PATH];
    DWORD length = GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) {
        complain(L"[MyWorld] 无法确定程序所在路径。\n");
        return 3;
    }

    wchar_t exe_dir[MAX_PATH];
    wcsncpy(exe_dir, exe_path, MAX_PATH - 1);
    exe_dir[MAX_PATH - 1] = L'\0';
    wchar_t *last_sep = wcsrchr(exe_dir, L'\\');
    if (last_sep != NULL) {
        *last_sep = L'\0';
    }

    /* 2. 校验项目根，避免 exe 被挪走后报出一堆莫名其妙的错误 */
    wchar_t entry[MAX_PATH];
    swprintf(entry, MAX_PATH, L"%ls\\myworld\\__main__.py", exe_dir);
    if (!file_exists(entry)) {
        wchar_t message[MAX_PATH + 256];
        swprintf(message, MAX_PATH + 256,
                 L"[MyWorld] 在 %ls 下找不到 myworld\\__main__.py。\n"
                 L"        请把 MyWorld.exe 放在项目根目录（与 myworld\\、web\\ 同级）。\n",
                 exe_dir);
        complain(message);
        pause_if_console();
        return 3;
    }

    /* 3. 解释器 */
    wchar_t python[MAX_PATH];
    int py_launcher = 0;
    if (!resolve_python(exe_dir, python, MAX_PATH, &py_launcher)) {
        complain(L"[MyWorld] 指定的 MYWORLD_PYTHON 不存在，或找不到可用的 Python。\n");
        int code = report_missing_runtime();
        pause_if_console();
        return code;
    }

    /* 4. 命令行 */
    wchar_t cmdline[CMDLINE_CAP];
    size_t used = 0;
    cmdline[0] = L'\0';

    /* 先扫一遍只属于启动器自己的开关：它们不会被转发给 Python */
    int explicit_open = -1; /* -1 未表态 / 1 要求开 / 0 要求关 */
    int print_args = 0;
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--print-args") == 0) {
            print_args = 1;
        } else if (wcscmp(argv[i], L"--open") == 0) {
            explicit_open = 1;
        } else if (wcscmp(argv[i], L"--no-open") == 0) {
            explicit_open = 0;
        }
    }

    if (!append_arg(cmdline, CMDLINE_CAP, &used, python)) {
        complain(L"[MyWorld] 命令行过长。\n");
        return 5;
    }
    if (py_launcher && !append_literal(cmdline, CMDLINE_CAP, &used, L" -3")) {
        complain(L"[MyWorld] 命令行过长。\n");
        return 5;
    }
    if (!append_literal(cmdline, CMDLINE_CAP, &used, L" -m myworld")) {
        complain(L"[MyWorld] 命令行过长。\n");
        return 5;
    }
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--print-args") == 0) {
            continue;
        }
        if (!append_literal(cmdline, CMDLINE_CAP, &used, L" ") ||
            !append_arg(cmdline, CMDLINE_CAP, &used, argv[i])) {
            complain(L"[MyWorld] 命令行过长。\n");
            return 5;
        }
    }

    /* 双击启动（有交互控制台）且用户没表态时，自己把页面弹出来 */
    if (explicit_open < 0 && console_is_interactive()) {
        if (!append_literal(cmdline, CMDLINE_CAP, &used, L" --open")) {
            complain(L"[MyWorld] 命令行过长。\n");
            return 5;
        }
    }

    if (print_args) {
        size_t need = wcslen(cmdline) + 32;
        wchar_t *message = (wchar_t *)malloc(need * sizeof(wchar_t));
        if (message != NULL) {
            swprintf(message, need, L"[cmdline] %ls\n", cmdline);
            write_stream(g_out, message);
            free(message);
        }
        return 0;
    }

    /* 5. 让 Python 一侧固定用 UTF-8，中文日志才不会在控制台变成乱码 */
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");

    /* 6. 启动并等待 */
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = g_in;
    si.hStdOutput = g_out;
    si.hStdError = g_err;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(python, cmdline, NULL, NULL, TRUE, 0, NULL, exe_dir, &si, &pi)) {
        wchar_t message[1024];
        swprintf(message, 1024,
                 L"[MyWorld] 启动失败（错误码 %lu）：%ls\n",
                 (unsigned long)GetLastError(), python);
        complain(message);
        pause_if_console();
        return 5;
    }

    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD exit_code = 0;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    CloseHandle(pi.hProcess);

    return (int)exit_code;
}
