#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601

#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <strsafe.h>
#include <stdbool.h>
#include <wchar.h>

#define APP_NAME L"Paper Monitor"
#define APP_USER_MODEL_ID L"DaheLabs.PaperMonitor"
#define TRAY_MUTEX_NAME L"Local\\PaperMonitorTray"
#define WINDOW_CLASS_NAME L"PaperMonitorNativeTrayWindow"
#define TRAY_CALLBACK_MESSAGE (WM_APP + 1)
#define TRAY_ICON_ID 1
#define MAX_COMMAND_CHARS 32768

enum MenuCommand {
    MENU_OPEN = 1001,
    MENU_SETTINGS,
    MENU_REFRESH,
    MENU_TEST_NOTIFICATION,
    MENU_QUIT,
};

typedef struct ProgramOptions {
    bool self_test;
    bool quit_existing;
} ProgramOptions;

static wchar_t g_app_path[MAX_COMMAND_CHARS];
static wchar_t g_config_path[MAX_COMMAND_CHARS];
static NOTIFYICONDATAW g_tray_icon;
static UINT g_taskbar_created_message;

static bool copy_text(wchar_t *destination, size_t count, const wchar_t *source) {
    return SUCCEEDED(StringCchCopyW(destination, count, source));
}

static bool contains_quote(const wchar_t *value) {
    return value != NULL && wcschr(value, L'"') != NULL;
}

static bool file_exists(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

static bool default_app_path(wchar_t *destination, size_t count) {
    wchar_t module_path[MAX_COMMAND_CHARS];
    DWORD length = GetModuleFileNameW(NULL, module_path, ARRAYSIZE(module_path));
    if (length == 0 || length >= ARRAYSIZE(module_path)) {
        return false;
    }
    wchar_t *separator = wcsrchr(module_path, L'\\');
    if (separator == NULL) {
        return false;
    }
    separator[1] = L'\0';
    return SUCCEEDED(StringCchPrintfW(destination, count, L"%sPaperMonitor.exe", module_path));
}

static bool default_config_path(wchar_t *destination, size_t count) {
    wchar_t app_data[MAX_PATH];
    HRESULT result = SHGetFolderPathW(
        NULL,
        CSIDL_APPDATA | CSIDL_FLAG_CREATE,
        NULL,
        SHGFP_TYPE_CURRENT,
        app_data
    );
    if (FAILED(result)) {
        return false;
    }
    return SUCCEEDED(StringCchPrintfW(
        destination,
        count,
        L"%s\\PaperMonitor\\config.json",
        app_data
    ));
}

static bool parse_options(ProgramOptions *options) {
    int argument_count = 0;
    wchar_t **arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (arguments == NULL) {
        return false;
    }

    bool ok = default_app_path(g_app_path, ARRAYSIZE(g_app_path))
        && default_config_path(g_config_path, ARRAYSIZE(g_config_path));
    for (int index = 1; ok && index < argument_count; ++index) {
        if (wcscmp(arguments[index], L"--app") == 0 && index + 1 < argument_count) {
            ok = copy_text(g_app_path, ARRAYSIZE(g_app_path), arguments[++index]);
        } else if (wcscmp(arguments[index], L"--config") == 0 && index + 1 < argument_count) {
            ok = copy_text(g_config_path, ARRAYSIZE(g_config_path), arguments[++index]);
        } else if (wcscmp(arguments[index], L"--self-test") == 0) {
            options->self_test = true;
        } else if (wcscmp(arguments[index], L"--quit-existing") == 0) {
            options->quit_existing = true;
        } else {
            ok = false;
        }
    }
    LocalFree(arguments);

    if (!ok || g_app_path[0] == L'\0' || g_config_path[0] == L'\0') {
        return false;
    }
    return !contains_quote(g_app_path) && !contains_quote(g_config_path);
}

static bool build_worker_command(
    const wchar_t *action,
    wchar_t *destination,
    size_t count
) {
    if (action == NULL || wcschr(action, L' ') != NULL || contains_quote(action)) {
        return false;
    }
    return SUCCEEDED(StringCchPrintfW(
        destination,
        count,
        L"\"%s\" %s --config \"%s\"",
        g_app_path,
        action,
        g_config_path
    ));
}

static void show_last_error(const wchar_t *context) {
    DWORD error = GetLastError();
    wchar_t system_message[512] = L"";
    FormatMessageW(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL,
        error,
        0,
        system_message,
        ARRAYSIZE(system_message),
        NULL
    );
    wchar_t message[768];
    if (FAILED(StringCchPrintfW(
        message,
        ARRAYSIZE(message),
        L"%s\n\nWindows error %lu: %s",
        context,
        error,
        system_message
    ))) {
        copy_text(message, ARRAYSIZE(message), context);
    }
    MessageBoxW(NULL, message, APP_NAME, MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
}

static bool launch_worker(const wchar_t *action) {
    wchar_t command_line[MAX_COMMAND_CHARS];
    if (!build_worker_command(action, command_line, ARRAYSIZE(command_line))) {
        SetLastError(ERROR_BAD_ARGUMENTS);
        show_last_error(L"Paper Monitor could not build the worker command.");
        return false;
    }

    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    BOOL created = CreateProcessW(
        g_app_path,
        command_line,
        NULL,
        NULL,
        FALSE,
        CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        NULL,
        NULL,
        &startup,
        &process
    );
    if (!created) {
        show_last_error(L"Paper Monitor could not start its short-lived worker process.");
        return false;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return true;
}

static void handle_menu_command(HWND window, UINT command) {
    switch (command) {
        case MENU_OPEN:
            launch_worker(L"window");
            break;
        case MENU_SETTINGS:
            launch_worker(L"settings");
            break;
        case MENU_REFRESH:
            launch_worker(L"scheduled-refresh");
            break;
        case MENU_TEST_NOTIFICATION:
            launch_worker(L"test-notification");
            break;
        case MENU_QUIT:
            DestroyWindow(window);
            break;
        default:
            break;
    }
}

static void show_tray_menu(HWND window) {
    HMENU menu = CreatePopupMenu();
    if (menu == NULL) {
        return;
    }
    AppendMenuW(menu, MF_STRING | MF_DEFAULT, MENU_OPEN, L"Open Paper Monitor");
    AppendMenuW(menu, MF_STRING, MENU_SETTINGS, L"Settings...");
    AppendMenuW(menu, MF_STRING, MENU_REFRESH, L"Refresh Now");
    AppendMenuW(menu, MF_STRING, MENU_TEST_NOTIFICATION, L"Test Notification");
    AppendMenuW(menu, MF_SEPARATOR, 0, NULL);
    AppendMenuW(menu, MF_STRING, MENU_QUIT, L"Quit Tray");
    SetMenuDefaultItem(menu, MENU_OPEN, FALSE);

    POINT cursor;
    GetCursorPos(&cursor);
    SetForegroundWindow(window);
    UINT command = TrackPopupMenu(
        menu,
        TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON,
        cursor.x,
        cursor.y,
        0,
        window,
        NULL
    );
    PostMessageW(window, WM_NULL, 0, 0);
    DestroyMenu(menu);
    handle_menu_command(window, command);
}

static bool add_tray_icon(HWND window) {
    ZeroMemory(&g_tray_icon, sizeof(g_tray_icon));
    g_tray_icon.cbSize = sizeof(g_tray_icon);
    g_tray_icon.hWnd = window;
    g_tray_icon.uID = TRAY_ICON_ID;
    g_tray_icon.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
    g_tray_icon.uCallbackMessage = TRAY_CALLBACK_MESSAGE;
    g_tray_icon.hIcon = LoadImageW(
        GetModuleHandleW(NULL),
        MAKEINTRESOURCEW(TRAY_ICON_ID),
        IMAGE_ICON,
        0,
        0,
        LR_DEFAULTSIZE | LR_SHARED
    );
    if (g_tray_icon.hIcon == NULL) {
        g_tray_icon.hIcon = LoadIconW(NULL, IDI_APPLICATION);
    }
    copy_text(g_tray_icon.szTip, ARRAYSIZE(g_tray_icon.szTip), APP_NAME);
    return Shell_NotifyIconW(NIM_ADD, &g_tray_icon) != FALSE;
}

static LRESULT CALLBACK tray_window_proc(
    HWND window,
    UINT message,
    WPARAM w_param,
    LPARAM l_param
) {
    if (message == g_taskbar_created_message) {
        add_tray_icon(window);
        return 0;
    }
    switch (message) {
        case TRAY_CALLBACK_MESSAGE:
            if ((UINT)l_param == WM_LBUTTONDBLCLK) {
                handle_menu_command(window, MENU_OPEN);
            } else if ((UINT)l_param == WM_RBUTTONUP || (UINT)l_param == WM_CONTEXTMENU) {
                show_tray_menu(window);
            }
            return 0;
        case WM_COMMAND:
            handle_menu_command(window, LOWORD(w_param));
            return 0;
        case WM_CLOSE:
            DestroyWindow(window);
            return 0;
        case WM_DESTROY:
            Shell_NotifyIconW(NIM_DELETE, &g_tray_icon);
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(window, message, w_param, l_param);
    }
}

static int run_self_test(void) {
    static const wchar_t *actions[] = {
        L"window",
        L"settings",
        L"scheduled-refresh",
        L"test-notification",
    };
    if (!file_exists(g_app_path)) {
        return 10;
    }
    for (size_t index = 0; index < ARRAYSIZE(actions); ++index) {
        wchar_t command[MAX_COMMAND_CHARS];
        if (!build_worker_command(actions[index], command, ARRAYSIZE(command))) {
            return 11;
        }
    }
    HICON icon = LoadImageW(
        GetModuleHandleW(NULL),
        MAKEINTRESOURCEW(TRAY_ICON_ID),
        IMAGE_ICON,
        0,
        0,
        LR_DEFAULTSIZE | LR_SHARED
    );
    return icon == NULL ? 12 : 0;
}

int WINAPI wWinMain(
    HINSTANCE instance,
    HINSTANCE previous_instance,
    PWSTR command_line,
    int show_command
) {
    (void)previous_instance;
    (void)command_line;
    (void)show_command;

    ProgramOptions options = {0};
    if (!parse_options(&options)) {
        MessageBoxW(
            NULL,
            L"Invalid tray arguments. Expected --app <exe> and --config <json>.",
            APP_NAME,
            MB_OK | MB_ICONERROR | MB_SETFOREGROUND
        );
        return 2;
    }
    if (options.self_test) {
        return run_self_test();
    }
    if (options.quit_existing) {
        HWND existing = FindWindowW(WINDOW_CLASS_NAME, NULL);
        if (existing != NULL) {
            PostMessageW(existing, WM_CLOSE, 0, 0);
        }
        return 0;
    }

    HANDLE mutex = CreateMutexW(NULL, TRUE, TRAY_MUTEX_NAME);
    if (mutex == NULL) {
        return 3;
    }
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(mutex);
        return 0;
    }

    SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID);
    g_taskbar_created_message = RegisterWindowMessageW(L"TaskbarCreated");

    WNDCLASSEXW window_class = {0};
    window_class.cbSize = sizeof(window_class);
    window_class.lpfnWndProc = tray_window_proc;
    window_class.hInstance = instance;
    window_class.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(TRAY_ICON_ID));
    window_class.hCursor = LoadCursorW(NULL, IDC_ARROW);
    window_class.lpszClassName = WINDOW_CLASS_NAME;
    if (RegisterClassExW(&window_class) == 0) {
        CloseHandle(mutex);
        return 4;
    }

    HWND window = CreateWindowExW(
        0,
        WINDOW_CLASS_NAME,
        APP_NAME,
        WS_OVERLAPPED,
        0,
        0,
        0,
        0,
        NULL,
        NULL,
        instance,
        NULL
    );
    if (window == NULL) {
        CloseHandle(mutex);
        return 5;
    }
    if (!add_tray_icon(window)) {
        DestroyWindow(window);
        CloseHandle(mutex);
        return 6;
    }

    MSG message;
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }

    CloseHandle(mutex);
    return (int)message.wParam;
}
