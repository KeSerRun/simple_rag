; RAG Simple Windows 安装程序脚本
; 需要先安装 Inno Setup: https://jrsoftware.org/isdl.php
;
; 编译:
;   iscc.exe scripts\installer.iss

#define MyAppName "RAG Simple"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "RAG-Simple"
#define MyAppURL "http://localhost:11000"
#define MyAppExeName "rag-simple.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\build\installer
OutputBaseFilename=RAG-Simple-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=lowest
CloseApplications=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
Source: "..\build\rag-simple\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /f /im rag-simple.exe 2>nul"; Flags: runhidden

[UninstallDelete]
; 清理运行时生成的用户数据和日志
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\.env"
Type: dirifempty; Name: "{app}"

[Code]
var
  ChatPage: TInputQueryWizardPage;
  OtherPage: TInputQueryWizardPage;

// 安装前杀掉残留进程，避免文件被锁
function InitializeSetup: Boolean;
var
  ResultCode: Integer;
begin
  Exec('cmd.exe', '/c taskkill /f /im rag-simple.exe 2>nul', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function GetChatKey: String;
begin
  Result := ChatPage.Values[0];
end;

function GetChatUrl: String;
begin
  Result := ChatPage.Values[1];
end;

function GetChatModel: String;
begin
  Result := ChatPage.Values[2];
end;

function GetEmbKey: String;
begin
  Result := OtherPage.Values[0];
end;

function GetEmbUrl: String;
begin
  Result := OtherPage.Values[1];
end;

function GetPdfKey: String;
begin
  Result := OtherPage.Values[2];
end;

function GetPdfUrl: String;
begin
  Result := OtherPage.Values[3];
end;

procedure InitializeWizard;
begin
  ChatPage := CreateInputQueryPage(
    wpSelectTasks,
    'API 密钥配置（1/2）',
    '对话模型配置',
    '填入你的 LLM 对话模型 API 信息。'
  );
  ChatPage.Add('对话模型 API Key (*)', False);
  ChatPage.Add('对话模型地址', False);
  ChatPage.Add('对话模型名称', False);
  ChatPage.Values[1] := 'https://opencode.ai/zen/go/v1';
  ChatPage.Values[2] := 'deepseek-v4-flash';

  OtherPage := CreateInputQueryPage(
    ChatPage.ID,
    'API 密钥配置（2/2）',
    '嵌入模型与 PDF 解析配置',
    '嵌入模型用于向量化，PDF 解析用于文档处理。非必填，可跳过后续再补充。'
  );
  OtherPage.Add('嵌入模型 API Key', False);
  OtherPage.Add('嵌入模型地址', False);
  OtherPage.Add('PDF 解析 API Key', False);
  OtherPage.Add('PDF 解析 Base URL', False);
  OtherPage.Values[1] := 'https://api.siliconflow.cn/v1';
  OtherPage.Values[3] := 'https://mineru.net/api/v4';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  IniPath: String;
begin
  if CurStep = ssPostInstall then begin
    IniPath := ExpandConstant('{app}\config.ini');

    if GetChatKey <> '' then
      SetIniString('api', 'chat_api_key', GetChatKey, IniPath);
    if GetChatUrl <> '' then
      SetIniString('api', 'chat_base_url', GetChatUrl, IniPath);
    if GetChatModel <> '' then
      SetIniString('api', 'chat_model', GetChatModel, IniPath);
    if GetEmbKey <> '' then
      SetIniString('api', 'embedding_api_key', GetEmbKey, IniPath);
    if GetEmbUrl <> '' then
      SetIniString('api', 'embedding_base_url', GetEmbUrl, IniPath);
    if GetPdfKey <> '' then
      SetIniString('api', 'mineru_api_key', GetPdfKey, IniPath);
    if GetPdfUrl <> '' then
      SetIniString('api', 'mineru_base_url', GetPdfUrl, IniPath);
  end;
end;
