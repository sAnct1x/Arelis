; Wraps win-installer/dist/Arelis into a single setup .exe.
;
; Run build.py first; this only packages what that produced. It is invoked with the
; version and the source tree passed in, so nothing here has to be edited per release:
;
;     ISCC.exe /DAppVersion=0.1.0 /DSourceTree=..\dist\Arelis win-installer\arelis.iss
;
; Per-user, and not by accident
; ============================
;
; PrivilegesRequired=lowest, which installs into %LOCALAPPDATA%\Programs\Arelis and never
; shows a UAC prompt. Three reasons, in order of how much they matter.
;
; Arelis is a single-user program. Its data root is already per-user, its scheduled tasks
; are registered for the current user, and its OAuth tokens belong to one person. An
; install into Program Files would be a machine-wide program with per-user everything.
;
; A per-user install can also be updated and removed by the person who installed it,
; which matters more than it sounds: an admin install of an unsigned program means an
; elevation prompt for an unsigned program, and that is the dialog people are right to
; refuse.
;
; And scheduled tasks are the reason it cannot be both. A task registered by an elevated
; install holds a path under Program Files while the data root stays under the user's
; profile, and the repointing logic in arelis/jobs/schedule.py is written for a program
; that moves, not for one whose two halves disagree about who owns them.
;
; Unsigned
; ========
;
; There is no code-signing certificate, so SmartScreen will warn on first download until
; enough people install it. Documented rather than hidden -- see the README beside this
; file -- and the published SHA-256 is what a cautious person can actually check.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceTree
  #define SourceTree "dist\Arelis"
#endif

#define AppName "Arelis"
#define AppPublisher "sAnct1x"
#define AppURL "https://github.com/sAnct1x/arelis"

[Setup]
; Never change this. It is the identity Windows uses to recognise an existing install, so
; a new value turns every update into a second copy in Apps & Features with the first one
; still installed and still holding scheduled tasks.
AppId={{8F4C2D31-6A5E-4B7C-9E1D-3A2F5B8C7D40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} setup

; %LOCALAPPDATA%\Programs\Arelis, because PrivilegesRequired is lowest.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\Lib\site-packages\arelis\assets\arelis.ico

; The bundled interpreter and every wheel in the lock are win_amd64. Refusing to install
; on anything else is better than installing and failing on the first import.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; The tree is around 640MB of mostly-compressible DLLs and Python source. Solid LZMA2 at
; max is slow to build and roughly halves what anybody has to download.
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
OutputDir=dist
OutputBaseFilename={#AppName}-{#AppVersion}-win64-setup
SetupIconFile=..\arelis\assets\arelis.ico
WizardStyle=modern

; AGPL. The obligation is to convey the licence with the program, and a wizard page
; nobody reads is still the honest place for it.
LicenseFile=..\LICENSE

; Arelis keeps a core process alive after the window closes, so an update will find files
; in use. Ask to close it rather than requiring a reboot to replace a DLL.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The whole built tree. recursesubdirs with an empty-directory sweep, because Qt's plugin
; layout and the Playwright driver both care about directories that exist.
Source: "{#SourceTree}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Runs before the new files are copied. Inno writes what it ships and deletes nothing else,
; so a file that used to be shipped and no longer is survives every upgrade forever. Arelis
; 0.1.0 shipped Scripts\arelis.exe and Scripts\arelisw.exe, pip-generated launchers holding
; the absolute path of the interpreter that built them, and anybody upgrading from it would
; keep two executables that name a directory on somebody else's computer. They are also
; exactly what an experienced person would try first on finding them.
Type: files; Name: "{app}\Scripts\arelis.exe"
Type: files; Name: "{app}\Scripts\arelisw.exe"

[Icons]
; pythonw.exe -m arelis, and not a launcher in Scripts. pip writes the absolute path of the
; interpreter that installed the wheel into every .exe launcher it generates, which during a
; build is the build directory -- a path that exists on one computer. A shortcut pointing at
; one of those would do nothing at all on anybody else's machine, and on the build machine it
; would silently run the build tree instead of the installed copy, which is why it took a
; while to notice. Worse, the only relocatable shebang those launchers accept is a bare name,
; resolved against PATH: measured here, that started an unrelated Python 3.11 and imported
; arelis from a source checkout. build.py deletes them and fails the build if they return.
;
; pythonw rather than python so no console flashes on launch, and -m arelis is the same entry
; point every scheduled task already uses.
;
; IconFilename is not optional: the icon of python.exe is a Python logo.
Name: "{group}\{#AppName}"; Filename: "{app}\pythonw.exe"; Parameters: "-m arelis"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\Lib\site-packages\arelis\assets\arelis.ico"; \
    Comment: "Arelis — local-first personal research assistant"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\pythonw.exe"; Parameters: "-m arelis"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\Lib\site-packages\arelis\assets\arelis.ico"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\pythonw.exe"; Parameters: "-m arelis"; WorkingDir: "{app}"; \
    Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

; The same launch for an update the program installed on its own. The entry above is a
; checkbox on the final wizard page, and skipifsilent means it does nothing in a silent
; run -- correct for the wizard, and it would leave a self-update ending with Arelis
; closed and no explanation. arelis/update.py passes /relaunch=yes; nothing else does, so
; a person running the setup with /SILENT by hand still gets the old quiet behaviour.
Filename: "{app}\pythonw.exe"; Parameters: "-m arelis"; WorkingDir: "{app}"; \
    Flags: nowait; Check: RelaunchRequested

[UninstallRun]
; The one thing an uninstaller here has to do beyond deleting files. A scheduled task
; holds an absolute path to this directory, so removing the directory without removing
; the tasks leaves Windows waking on a timer to run something that is gone -- silently,
; because a scheduled task that cannot start shows nobody anything.
;
; python.exe with runhidden rather than pythonw.exe: the console build has somewhere to
; write, and runhidden means nobody sees the window. The flag is handled before the
; configuration is read, so an unreadable config does not leave the tasks behind.
;
; The interpreter directly, for the same reason as the shortcuts: this used to name
; Scripts\arelis.exe, whose baked-in interpreter path does not exist on the machine being
; uninstalled. It would have failed silently and left the scheduled tasks behind -- the exact
; outcome this entry exists to prevent.
;
; RunOnceId keeps it to one execution across repeated uninstall attempts.
Filename: "{app}\python.exe"; Parameters: "-m arelis --remove-scheduled-tasks"; \
    WorkingDir: "{app}"; Flags: runhidden skipifdoesntexist; \
    RunOnceId: "RemoveScheduledTasks"

[UninstallDelete]
; Bytecode written after install, which is not in the file list and would otherwise
; leave the directory behind.
Type: filesandordirs; Name: "{app}\Lib\site-packages\__pycache__"

; Deliberately absent: anything under %LOCALAPPDATA%\Arelis. That is conversations,
; memory, saved jobs, OAuth tokens and downloaded models -- the user's data, not the
; program's, and an uninstaller is not the place to decide it should go. Reinstalling
; picks it back up, which is the behaviour somebody moving to a new version wants.

; Last on purpose: everything after [Code] is Pascal, so a section placed below it would be
; read as source and silently stop being a section.
[Code]
function RelaunchRequested(): Boolean;
begin
  Result := CompareText(ExpandConstant('{param:relaunch|no}'), 'yes') = 0;
end;
