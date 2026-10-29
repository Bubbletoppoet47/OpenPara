; Inno Setup script - builds OpenPara-Setup-<version>.exe from build\OpenPara (made by .github/workflows/release.yml)
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6C1F3E0B-3B63-4C0A-9E57-0A9A3D1C0A11}
AppName=OpenPara
AppVersion={#Version}
AppPublisher=OpenPara
AppPublisherURL=https://github.com/Bubbletoppoet47/OpenPara
DefaultDirName={localappdata}\Programs\OpenPara
DefaultGroupName=OpenPara
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=OpenPara-Setup-{#Version}
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
Name: "assoc"; Description: "Open .gpd / .gpa / .gps / .gpr files with OpenPara"; GroupDescription: "File types:"

[Files]
Source: "..\build\OpenPara\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\OpenPara"; Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\OpenPara.ico"
Name: "{userdesktop}\OpenPara"; Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\OpenPara.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\.gpd"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gpa"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gps"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\.gpr"; ValueType: string; ValueData: "OpenPara.file"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file"; ValueType: string; ValueData: "OpenPara document"; Flags: uninsdeletekey; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file\DefaultIcon"; ValueType: string; ValueData: "{app}\app\OpenPara.ico"; Tasks: assoc
Root: HKCU; Subkey: "Software\Classes\OpenPara.file\shell\open\command"; ValueType: string; ValueData: """{app}\python\OpenPara.exe"" ""{app}\app\gpd_app.py"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\python\OpenPara.exe"; Parameters: """{app}\app\gpd_app.py"""; WorkingDir: "{app}"; Description: "Start OpenPara"; Flags: nowait postinstall skipifsilent
