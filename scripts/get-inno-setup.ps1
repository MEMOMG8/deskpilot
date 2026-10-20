# Portable build tool only: no machine installation, associations or PATH edits.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolRoot = Join-Path $RepoRoot "build\tools"
$ToolDir = Join-Path $ToolRoot "inno-6.7.3"
$Compiler = Join-Path $ToolDir "ISCC.exe"
$Download = Join-Path $ToolRoot "innosetup-6.7.3.exe"
$ExpectedHash = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"

if (Test-Path -LiteralPath $Compiler) {
    Write-Output $Compiler
    exit 0
}
New-Item -ItemType Directory -Path $ToolRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $Download)) {
    Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe" -OutFile $Download
}
if ((Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedHash) {
    throw "Inno Setup download checksum mismatch. Nothing executed."
}
$Signature = Get-AuthenticodeSignature -LiteralPath $Download
if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notlike "*Pyrsys B.V.*") {
    throw "Inno Setup publisher signature did not validate. Nothing executed."
}
$Arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER", "/PORTABLE=1", "/DIR=`"$ToolDir`"")
$Process = Start-Process -FilePath $Download -ArgumentList $Arguments -WindowStyle Hidden -PassThru -Wait
if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Compiler)) {
    throw "Portable compiler preparation failed: $($Process.ExitCode)"
}
Write-Output $Compiler
