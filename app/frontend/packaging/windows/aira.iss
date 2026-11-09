; Пилотный установщик AIRA для Windows (Inno Setup 6). Собирается из build.ps1:
;   ISCC /DSourceDir=<папка stage> /DAppVersion=0.1.0 aira.iss
; Ставится для текущего пользователя, без прав администратора.

#ifndef SourceDir
  #error Укажите /DSourceDir=<папка stage из build.ps1>
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{060823CE-6FB7-4DDF-8A22-32653BC929AE}
AppName=AIRA
AppVersion={#AppVersion}
AppVerName=AIRA {#AppVersion} (пилотная сборка)
AppPublisher=Команда AIRA
AppComments=Проверка требований: размытые формулировки, дубли и противоречия. Работает на этом компьютере.
; Обычно %LOCALAPPDATA%\Programs\AIRA. Если в профиле русские буквы и у Windows нет коротких латинских
; имён папок, — C:\AIRA: встроенный PostgreSQL не работает с кириллицей в пути.
DefaultDirName={code:DefaultDir}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=AIRA-Setup-{#AppVersion}
SetupIconFile={#SourceDir}\launcher\aira.ico
UninstallDisplayIcon={app}\launcher\aira.ico
UninstallDisplayName=AIRA
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
; Пока AIRA запущена, установщик и удаление попросят её закрыть.
AppMutex=AIRA-Launcher

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AIRA"; Filename: "{app}\python\pythonw.exe"; Parameters: "-s -E ""{app}\launcher\aira_launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\launcher\aira.ico"; Comment: "AIRA — проверка требований"
Name: "{autodesktop}\AIRA"; Filename: "{app}\python\pythonw.exe"; Parameters: "-s -E ""{app}\launcher\aira_launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\launcher\aira.ico"; Comment: "AIRA — проверка требований"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-s -E ""{app}\launcher\aira_launcher.pyw"""; WorkingDir: "{app}"; Description: "Запустить AIRA"; Flags: postinstall nowait skipifsilent

; Automatic update launches the new app; a silent administrative install does not.
Filename: "{app}\python\pythonw.exe"; Parameters: "-s -E ""{app}\launcher\aira_launcher.pyw"""; WorkingDir: "{app}"; Flags: nowait skipifnotsilent; Check: IsAutomaticUpdate

[UninstallRun]
; Если база осталась запущенной после сбоя — остановить её перед удалением файлов.
Filename: "{app}\python\python.exe"; Parameters: "-s -E ""{app}\launcher\aira_launcher.pyw"" --stop-db"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "StopAiraPostgres"

[UninstallDelete]
; Кэш Python (__pycache__), созданный во время работы. Документы и база лежат отдельно, в %LOCALAPPDATA%\AIRA.
Type: filesandordirs; Name: "{app}"

[Code]
function IsAutomaticUpdate: Boolean;
begin
  Result := ExpandConstant('{param:AIRAUPDATE|0}') = '1';
end;

function IsAscii(S: String): Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to Length(S) do
    if Ord(S[I]) > 127 then
    begin
      Result := False;
      Exit;
    end;
end;

function DefaultDir(Param: String): String;
begin
  Result := ExpandConstant('{localappdata}\Programs\AIRA');
  if not IsAscii(GetShortName(ExpandConstant('{localappdata}'))) then
    Result := ExpandConstant('{sd}\AIRA');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\AIRA');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox('Удалить также документы, результаты проверок и базу AIRA на этом компьютере?' + #13#10#13#10 +
                'Если вы собираетесь установить AIRA снова и сохранить документы, нажмите «Нет».',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
