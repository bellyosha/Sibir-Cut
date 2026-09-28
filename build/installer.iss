#define MyAppName "Sibir Cut"
#define MyAppVersion "0.3.1"
#define MyAppExeName "SibirCut.exe"

[Setup]
AppId={{0F38D788-9A41-4E9B-9DDA-5FC5E88B9301}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\Sibir Cut
DefaultGroupName=Sibir Cut
OutputDir=..\dist
OutputBaseFilename=Sibir_Cut_Setup_0.3.1_x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\SibirCut.ico

[InstallDelete]
Type: files; Name: "{app}\NovatechCut.exe"
Type: files; Name: "{group}\Novatech Cut.lnk"
Type: files; Name: "{autodesktop}\Novatech Cut.lnk"

[Files]
Source: "..\dist\SibirCut.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Sibir Cut"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Sibir Cut"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Sibir Cut"; Flags: nowait postinstall skipifsilent
