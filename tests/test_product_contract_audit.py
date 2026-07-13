import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class ProductContractAuditTests(unittest.TestCase):
    def test_windows_tray_dashboard_actions_use_native_window_entrypoint(self):
        source = read_text("paper_monitor/windows_tray.py")
        window_source = read_text("paper_monitor/windows_app_window.py")

        self.assertIn("def app_window_command", source)
        self.assertIn("def tray_process_command", source)
        self.assertIn("def launch_app_window", source)
        self.assertIn("class RefreshReason", source)
        self.assertIn('pystray.MenuItem("Open Paper Monitor"', source)
        self.assertIn("WM_LBUTTONDBLCLK", source)
        self.assertIn("def _tray_icon_class", source)
        self.assertIn("def _open_app_window_once", source)
        self.assertIn("def focus_existing_app_window", source)
        self.assertIn("def show_window_launch_error", source)
        self.assertIn("WINDOW_MUTEX_NAME", source)
        self.assertIn('self._open_app_window_once("/")', source)
        self.assertIn('self._open_app_window_once("/settings")', source)
        self.assertIn("from .windows_mutex import", source)
        self.assertIn("from .windows_mutex import", window_source)
        self.assertNotIn("def _create_mutex", source)
        self.assertNotIn("def _open_mutex", source)
        self.assertNotIn("def _create_mutex", window_source)
        self.assertNotIn("def _last_error", window_source)
        self.assertNotIn("dashboard_server_factory", source)
        self.assertNotIn("_dashboard_server", source)
        self.assertNotIn("default=True", source)
        self.assertNotIn("primary-click activation", source)
        self.assertNotIn("import webview", source)
        self.assertNotIn("webview.start", source)
        self.assertNotIn("self.open_url", source)

    def test_windows_window_startup_defers_nonessential_feature_imports(self):
        tray = read_text("paper_monitor/windows_tray.py")
        window = read_text("paper_monitor/windows_app_window.py")
        server = read_text("paper_monitor/windows_dashboard_server.py")

        self.assertNotIn("\nfrom .app_refresh import", tray)
        self.assertIn('"scheduled-refresh"', tray)
        self.assertIn("def _sync_windows_runtime_settings", tray)
        self.assertNotIn("\nfrom .windows_scheduled_task import", tray)
        self.assertNotIn("\nfrom .windows_dashboard_server import", window)
        self.assertIn("def _default_dashboard_server_factory", window)
        self.assertNotIn("\nfrom .analysis_refresh import", server)
        self.assertNotIn("\nfrom .windows_settings import", server)
        self.assertIn("def _default_keyword_analysis_runner", server)

    def test_tray_and_status_dashboard_actions_do_not_use_cli_or_browser_openers(self):
        windows_tray = read_text("paper_monitor/windows_tray.py")
        macos_app_delegate = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/AppDelegate.swift")
        macos_click_policy = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/StatusItemClickPolicy.swift")

        self.assertNotIn("open-dashboard", windows_tray)
        self.assertNotIn("webbrowser.open", windows_tray)
        self.assertNotIn("os.startfile", windows_tray)

        status_start = macos_app_delegate.index("private func statusMenu()")
        status_end = macos_app_delegate.index("@objc private func statusOpenSettings()")
        status_actions = macos_app_delegate[status_start:status_end]
        self.assertIn('action: #selector(statusOpenDashboard)', status_actions)
        self.assertIn("openDashboard()", status_actions)
        self.assertNotIn("NSWorkspace.shared.open", status_actions)
        self.assertNotIn("open-dashboard", status_actions)
        self.assertNotIn("NSWorkspace.shared.open", macos_click_policy)

    def test_windows_background_monitoring_is_nonresident(self):
        source = read_text("paper_monitor/windows_tray.py")
        schedule = read_text("paper_monitor/windows_scheduled_task.py")
        install = read_text("windows/Install-PaperMonitor.ps1")

        self.assertIn('"scheduled-refresh"', source)
        self.assertIn('"MultipleInstancesPolicy"', schedule)
        self.assertIn('"RunOnlyIfNetworkAvailable"', schedule)
        self.assertIn('"InteractiveToken"', schedule)
        self.assertIn("install-startup --config $Config", install)
        self.assertNotIn('Start-Process -FilePath $InstalledExe -ArgumentList @("tray", "--quiet")', install)
        self.assertIn('Start-Process -FilePath $InstalledExe', install)

    def test_macos_launch_refresh_is_only_wired_from_application_launch(self):
        app_delegate = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/AppDelegate.swift")
        lifecycle = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/LaunchLifecycle.swift")

        did_finish_start = app_delegate.index("public func applicationDidFinishLaunching")
        reopen_start = app_delegate.index("public func applicationShouldHandleReopen")
        did_finish = app_delegate[did_finish_start:reopen_start]
        self.assertIn("requestNotificationAuthorizationThenRefresh", did_finish)
        self.assertIn("launchReason: launchOptions.launchReason", did_finish)
        self.assertIn("if launchReason == .loginStartup", app_delegate)

        reopen_end = app_delegate.index("public func applicationShouldTerminateAfterLastWindowClosed")
        reopen = app_delegate[reopen_start:reopen_end]
        self.assertNotIn("runLaunchRefreshIfNeeded", reopen)
        self.assertNotIn("LaunchRefreshPolicy", reopen)
        self.assertNotIn("applicationDidBecomeActive", app_delegate)
        self.assertNotIn("didWake", app_delegate)
        self.assertIn('case processLaunch = "process_launch"', lifecycle)
        self.assertIn('case loginStartup = "login_startup"', lifecycle)
        self.assertIn('case manualRefresh = "manual_refresh"', lifecycle)
        self.assertIn('case scheduledRefresh = "scheduled_refresh"', lifecycle)

    def test_windows_release_keeps_portable_artifacts(self):
        package_script = read_text("scripts/package_windows_release.ps1")

        self.assertIn('$ZipPath = Join-Path $OutputDir "$ReleaseName.zip"', package_script)
        self.assertIn('$ExeAssetPath = Join-Path $OutputDir "$ReleaseName.exe"', package_script)
        self.assertIn('$InstallerBaseName = "$ReleaseName-Setup"', package_script)
        self.assertIn('$InstallerPath = Join-Path $OutputDir "$InstallerBaseName.exe"', package_script)
        self.assertIn("Compress-Archive", package_script)
        self.assertIn('build_windows_app.ps1") -Version $Version', package_script)
        self.assertIn("Copy-ReleaseFile -Source $DistExe -Destination $ExeAssetPath", package_script)
        self.assertIn('$DistAppDir = Join-Path $Root "dist\\windows\\PaperMonitor"', package_script)
        self.assertIn('Copy-Item -Path (Join-Path $DistAppDir "*")', package_script)
        self.assertIn("$AssetPaths += @($ZipPath, $ExeAssetPath)", package_script)
        self.assertIn('"SHA256SUMS-$Version.txt"', package_script)
        self.assertIn('"CURRENT_WINDOWS_RELEASE.txt"', package_script)
        self.assertIn("Move-Item -LiteralPath $CurrentReleaseTemp", package_script)
        self.assertNotIn(
            'Copy-ReleaseFile -Source (Join-Path $Root "windows\\Install-PaperMonitor.ps1")',
            package_script,
        )

    def test_github_windows_release_uploads_complete_artifact_set(self):
        workflow = read_text(".github/workflows/build-windows.yml")

        self.assertIn("package_windows_release.ps1 @parameters", workflow)
        self.assertIn("Paper-Monitor-Windows-${{ steps.version.outputs.version }}-Setup.exe", workflow)
        self.assertIn("Paper-Monitor-Windows-${{ steps.version.outputs.version }}.zip", workflow)
        self.assertIn("Paper-Monitor-Windows-${{ steps.version.outputs.version }}.exe", workflow)
        self.assertIn("SHA256SUMS-${{ steps.version.outputs.version }}.txt", workflow)
        self.assertIn("WINDOWS_SIGNING_CERTIFICATE_BASE64", workflow)
        self.assertIn("RequireSignature", workflow)

    def test_windows_dependency_lock_is_used_for_reproducible_builds(self):
        ci_workflow = read_text(".github/workflows/ci.yml")
        release_workflow = read_text(".github/workflows/build-windows.yml")
        prepare_script = read_text("scripts/prepare_windows_project.py")

        for workflow in (ci_workflow, release_workflow):
            self.assertIn("cache-dependency-path: requirements-windows.lock.txt", workflow)
            self.assertIn("python -m pip install -r requirements-windows.lock.txt", workflow)
        self.assertIn("python -m pip_audit -r requirements-windows.lock.txt", ci_workflow)
        self.assertIn('"requirements-windows.lock.txt"', prepare_script)
        for readme_path in ("README.md", "README.zh-CN.md", "README_WINDOWS.md"):
            self.assertIn(
                "python -m pip install -r requirements-windows.lock.txt",
                read_text(readme_path),
            )

    def test_source_hygiene_excludes_runtime_and_archive_data(self):
        ignore = read_text(".gitignore")
        attributes = read_text(".gitattributes")
        editor_config = read_text(".editorconfig")
        quality_config = read_text("pyproject.toml")
        ci_workflow = read_text(".github/workflows/ci.yml")

        for entry in (".venv/", "build/", "dist/", "public_release/", "config.json", "*.sqlite3", ".agents/"):
            self.assertIn(entry, ignore)
        for entry in (".coverage", ".coverage.*", "coverage.xml", "htmlcov/", "*.log"):
            self.assertIn(entry, ignore)
        self.assertIn("旧的归档文件夹/", ignore)
        self.assertIn("* text=auto eol=lf", attributes)
        self.assertIn("charset = utf-8", editor_config)
        self.assertIn("end_of_line = lf", editor_config)
        self.assertIn("insert_final_newline = true", editor_config)
        self.assertIn("[*.{bat,cmd}]\nend_of_line = crlf", editor_config)
        self.assertIn("[*.md]\ntrim_trailing_whitespace = false", editor_config)
        self.assertIn('select = ["E4", "E7", "E9", "F", "I"]', quality_config)
        self.assertNotIn("if: ${{ hashFiles(", ci_workflow)
        self.assertIn("push:\n    branches:\n      - main", ci_workflow)
        self.assertIn("python -m coverage run -m unittest discover -s tests", ci_workflow)
        self.assertIn("python -m coverage report --fail-under=70", ci_workflow)

    def test_windows_release_installer_registers_in_installed_apps(self):
        installer = read_text("windows/PaperMonitor.iss")
        package_script = read_text("scripts/package_windows_release.ps1")

        self.assertIn("[Setup]", installer)
        self.assertIn("AppId=", installer)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\PaperMonitor", installer)
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn("UninstallFilesDir={app}\\Uninstall", installer)
        self.assertIn("UninstallDisplayIcon={app}\\PaperMonitor.exe", installer)
        self.assertIn('Name: "{group}\\Paper Monitor"', installer)
        self.assertNotIn('Name: "{group}\\Settings"; Filename:', installer)
        self.assertIn('Type: files; Name: "{group}\\Settings.lnk"', installer)
        self.assertIn('Name: "{group}\\Uninstall Paper Monitor"', installer)
        self.assertIn('Name: "{autodesktop}\\Paper Monitor"', installer)
        self.assertIn("Tasks: desktopicon", installer)
        self.assertNotIn('Name: "startup"', installer)
        self.assertNotIn("ValueData:", installer)
        self.assertIn("Flags: unchecked", installer)
        self.assertNotIn("Tasks: startup", installer)
        self.assertIn("RemoveScheduledRefreshTask", installer)
        self.assertIn("schtasks.exe", installer)
        self.assertIn('Parameters: "sync-runtime"', installer)
        self.assertIn("runhidden waituntilterminated", installer)
        self.assertIn("RegDeleteValue(HKCU", installer)
        self.assertIn('Type: files; Name: "{app}\\unins000.dat"', installer)
        self.assertIn('Type: files; Name: "{app}\\unins000.exe"', installer)
        self.assertIn("postinstall skipifsilent unchecked", installer)
        self.assertNotIn("{userappdata}\\PaperMonitor\\config.json", installer)
        self.assertIn("VersionInfoVersion={#GetVersionNumbersString", installer)
        self.assertIn("VersionInfoProductTextVersion={#MyAppVersion}", installer)
        self.assertIn("recursesubdirs createallsubdirs", installer)

        self.assertIn("$InnoScript = Join-Path $Root \"windows\\PaperMonitor.iss\"", package_script)
        self.assertIn("function Find-InnoSetupCompiler", package_script)
        self.assertIn('"Inno Setup 7\\ISCC.exe"', package_script)
        self.assertIn('"Inno Setup 6\\ISCC.exe"', package_script)
        self.assertIn("/DSourceDir=$StagingDir", package_script)
        self.assertIn("/DOutputBaseFilename=$InstallerBaseName", package_script)
        self.assertIn("$AssetPaths += $InstallerPath", package_script)
        self.assertIn("function Find-SignTool", package_script)
        self.assertIn("function Invoke-CodeSign", package_script)
        self.assertIn("CodeSigningCertificateThumbprint", package_script)
        self.assertIn("RequireSignature", package_script)
        self.assertIn("BuiltProductVersion", package_script)
        self.assertIn("does not match release version", package_script)
        self.assertIn("InstallerProductVersion", package_script)
        self.assertIn("InstallerFileVersion", package_script)

    def test_release_notes_document_installer_portable_and_nonresident_refresh(self):
        notes = read_text("docs/RELEASE_NOTES.md")

        self.assertIn("installer", notes.lower())
        self.assertIn("portable", notes.lower())
        self.assertIn("Windows Task Scheduler", notes)
        self.assertIn("exits", notes)
        self.assertIn("no Paper Monitor process", notes)

    def test_macos_status_item_primary_click_opens_dashboard_not_menu(self):
        app_delegate = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/AppDelegate.swift")
        click_policy = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/StatusItemClickPolicy.swift")

        self.assertNotIn("statusItem?.menu = statusMenu()", app_delegate)
        self.assertIn("statusItem?.button?.action", app_delegate)
        self.assertIn("statusItem?.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])", app_delegate)
        self.assertIn("case .rightMouseDown, .rightMouseUp:", click_policy)
        self.assertIn("return .openDashboard", click_policy)

    def test_ui_date_formatting_is_locale_independent_english(self):
        dashboard = read_text("paper_monitor/dashboard.py")
        date_utils = read_text("paper_monitor/date_utils.py")
        menu = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/AppMainMenuController.swift")
        swift_formatter = read_text("macos/PaperMonitorApp/Sources/PaperMonitorCore/EnglishDateFormatter.swift")

        self.assertIn("format_display_date", date_utils)
        self.assertIn('Intl.DateTimeFormat("en-US"', dashboard)
        self.assertNotIn('strftime("%b %d")', dashboard)
        self.assertNotIn("toLocaleDateString", dashboard)
        self.assertIn("EnglishDateFormatter.compactDateTime", menu)
        self.assertNotIn("DateFormatter.localizedString", menu)
        self.assertIn('Locale(identifier: "en_US_POSIX")', swift_formatter)
