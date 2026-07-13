#define MyAppName "Paper Monitor"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
#define SourceDir "..\dist\windows"
#endif
#ifndef OutputDir
#define OutputDir "..\public_release"
#endif
#ifndef OutputBaseFilename
#define OutputBaseFilename "Paper-Monitor-Windows-Setup"
#endif
#ifndef IconFile
#define IconFile "assets\PaperMonitor.ico"
#endif

[Setup]
AppId={{18E4473D-7AF9-4F2D-9A64-5E6E53B6A9E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Paper Monitor
AppPublisherURL=https://github.com/Dahe-Labs/paper-monitor
AppSupportURL=https://github.com/Dahe-Labs/paper-monitor/issues
AppUpdatesURL=https://github.com/Dahe-Labs/paper-monitor/releases
VersionInfoCompany=Paper Monitor
VersionInfoDescription=Paper Monitor Setup
VersionInfoOriginalFileName={#OutputBaseFilename}.exe
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#GetVersionNumbersString(SourceDir + "\PaperMonitor.exe")}
VersionInfoProductTextVersion={#MyAppVersion}
VersionInfoVersion={#GetVersionNumbersString(SourceDir + "\PaperMonitor.exe")}
VersionInfoTextVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\PaperMonitor
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=no
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#IconFile}
UninstallFilesDir={app}\Uninstall
UninstallDisplayIcon={app}\PaperMonitor.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\unins000.dat"
Type: files; Name: "{app}\unins000.exe"
Type: files; Name: "{group}\Settings.lnk"
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Paper Monitor"; Filename: "{app}\PaperMonitor.exe"; Parameters: "window"; WorkingDir: "{app}"; AppUserModelID: "DaheLabs.PaperMonitor"
Name: "{group}\Uninstall Paper Monitor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Paper Monitor"; Filename: "{app}\PaperMonitor.exe"; Parameters: "window"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "DaheLabs.PaperMonitor"

[Run]
Filename: "{app}\PaperMonitor.exe"; Parameters: "sync-runtime"; Flags: runhidden waituntilterminated
Filename: "{app}\PaperMonitor.exe"; Parameters: "window"; Description: "Launch Paper Monitor"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{app}\PaperMonitor.exe"; Parameters: "uninstall-startup"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
procedure RemoveScheduledRefreshTask;
var
  ResultCode: Integer;
begin
  { The application files may be gone after uninstall, so remove the task directly. }
  Exec(
    ExpandConstant('{sys}\schtasks.exe'),
    '/Delete /TN "\PaperMonitor Scheduled Refresh" /F',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveScheduledRefreshTask;
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PaperMonitor');
  end;
end;
