; Inno Setup script - builds OpenPara-Setup-<version>.exe from build\OpenPara (made by .github/workflows/release.yml)
#ifndef Version
  #define Version "0.0.0"
#endif
; /DPlayground=1 builds the OpenPara Playground (dev channel): another name, id, folder and shortcuts, so it installs next to OpenPara
#ifdef Playground
  #define AppTitle "OpenPara Playground"
  #define AppGuid "{{6C1F3E0B-3B63-4C0A-9E57-0A9A3D1C0B22}"
  #define FilePrefix "OpenPara-Playground-Setup-"
#else
  #define AppTitle "OpenPara"
  #define AppGuid "{{6C1F3E0B-3B63-4C0A-9E57-0A9A3D1C0A11}"
  #define FilePrefix "OpenPara-Setup-"
#endif

[Setup]
AppId={#AppGuid}
AppName={#AppTitle}
AppVersion={#Version}
AppPublisher=OpenPara
AppPublisherURL=https://github.com/Bubbletoppoet47/OpenPara
DefaultDirName={localappdata}\Programs\{#AppTitle}
DefaultGroupName={#AppTitle}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#FilePrefix}{#Version}
SetupIconFile=..\OpenPara.ico
UninstallDisplayIcon={app}\app\OpenPara.ico
LicenseFile=..\LICENSE
Compression=lzma2/normal
SolidCompression=yes
ArchitecturesAllowed=x64compatible
WizardStyle=modern
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
#ifndef Playground
Name: "assoc"; Description: "Open .gpd / .gpa / .gps / .gpr files with OpenPara"; GroupDescription: "File types:"
#endif

[Files]
Source: "..\build\OpenPara\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#AppTitle}"; Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\OpenPara.ico"
Name: "{userdesktop}\{#AppTitle}"; Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\OpenPara.ico"; Tasks: desktopicon

#ifndef Playground
[Registry]
Root: HKCU; Subkey: "Software\Classes\.gpd"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gpa"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gps"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gpr"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file"; ValueType: string; ValueData: "OpenPara document"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file\DefaultIcon"; ValueType: string; ValueData: "{app}\app\OpenPara.ico"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file\shell\open\command"; ValueType: string; ValueData: """{app}\python\OpenPara.exe"" ""{app}\app\gpd_app.py"" ""%1"""; Tasks: assoc
#endif

[Run]
Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; Description: "Start {#AppTitle}"; Flags: nowait postinstall skipifsilent
