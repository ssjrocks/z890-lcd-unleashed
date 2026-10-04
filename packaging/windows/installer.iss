; Inno Setup script for Z890 LCD Unleashed (Windows). Build after PyInstaller:
;   iscc /DAppVersion=0.2.0 packaging\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Z890 LCD Unleashed"
#define AppExe "z890-lcd-gui.exe"
#define ServiceExe "z890-lcd-service.exe"

[Setup]
AppId={{6B0E2C47-3D8B-4C8E-9E1B-2A7F9C1D5E83}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ssjrocks
AppPublisherURL=https://github.com/ssjrocks/z890-lcd-unleashed
AppSupportURL=https://github.com/ssjrocks/z890-lcd-unleashed/issues
DefaultDirName={autopf}\Z890 LCD Unleashed
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=z890-lcd-unleashed-{#AppVersion}-windows-setup
SetupIconFile=z890-lcd.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=force

[Tasks]
Name: "autostart"; Description: "Start the background service when I sign in (keeps stats and slideshows running)"; GroupDescription: "Background service:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\z890-lcd\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Z890 LCD Unleashed"; ValueData: """{app}\{#ServiceExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#ServiceExe}"; Flags: nowait runasoriginaluser; Tasks: autostart
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#ServiceExe}"; Flags: runhidden; RunOnceId: "StopService"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopGui"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { stop a running copy before files are replaced on upgrade }
  if CurStep = ssInstall then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#ServiceExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
