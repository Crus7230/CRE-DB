[CmdletBinding()]
param(
    [string]$CandidateRoot = (Join-Path $PSScriptRoot "..\.."),

    [string[]]$CredentialEnvironmentFiles = @(
        "C:\10137_WorkSpace\env\.env.personal.txt",
        "C:\10137_WorkSpace\env\.env"
    ),

    [string]$OutgoingBaseline = "eef5faf",

    [int64]$MaximumTextFileBytes = 10485760
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string[]]$GitArgs
    )

    $result = @(& git -C $Repository @GitArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "git failed in ${Repository}: git $($GitArgs -join ' ')"
    }
    return $result
}

function Test-ForbiddenReleasePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = $RelativePath.Replace("\", "/")
    if ($path -match "(?i)(^|/)[.]git(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]vercel(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(node_modules|[.]next(?:-[^/]+)?)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)(data|backups?|raw|artifacts?|reports?|logs)(/|$)") { return $true }
    if ($path -match "(?i)(^|/)[.]env($|[.])" -and $path -notmatch "(?i)(^|/)[.]env[.]example$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3|pem|key|p12|pfx)$") { return $true }
    if ($path -match "(?i)[.](db|sqlite|sqlite3)-(wal|shm)$") { return $true }
    if ($path -match "(?i)(^|/)(a?c+ess[- _]?code|credential|secret)([^/]*)(/|$)") { return $true }
    return $false
}

function Read-CredentialInventory {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    $values = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $candidateCount = 0
    $environmentFileCount = 0
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $environmentFileCount++
        foreach ($line in Get-Content -LiteralPath $path) {
            if ($line -notmatch "^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$") { continue }
            $name = $matches[1]
            $rawValue = $matches[2]
            # Credential-free service endpoints are public identifiers, not secrets.
            # Credential-bearing URLs remain covered by DATABASE_URL/DSN.
            if ($name -notmatch "(?i)(TOKEN|SECRET|PASSWORD|PASS|KEY|DSN|DATABASE_URL|TURSO_DATABASE_URL|VERCEL_TOKEN)") { continue }
            $value = $rawValue.Trim()
            if ($value.Length -ge 2) {
                $first = $value[0]
                $last = $value[$value.Length - 1]
                if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            if ([string]::IsNullOrWhiteSpace($value)) { continue }
            $candidateCount++
            [void]$values.Add($value)
        }
    }
    return [pscustomobject]@{
        EnvironmentFileCount = $environmentFileCount
        CandidateCount = $candidateCount
        Values = $values
    }
}

function Read-GitBlobText {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$ObjectId
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git"
    [void]$startInfo.ArgumentList.Add("-C")
    [void]$startInfo.ArgumentList.Add($Repository)
    [void]$startInfo.ArgumentList.Add("cat-file")
    [void]$startInfo.ArgumentList.Add("blob")
    [void]$startInfo.ArgumentList.Add($ObjectId)
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $content = $process.StandardOutput.ReadToEnd()
    [void]$process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "git cat-file failed for an outgoing blob" }
    return $content
}

$candidateResolved = (Resolve-Path -LiteralPath $CandidateRoot).Path
$candidateRootFull = [string](Invoke-GitLines -Repository $candidateResolved -GitArgs @("rev-parse", "--show-toplevel") | Select-Object -First 1)
$candidateRootFull = [IO.Path]::GetFullPath($candidateRootFull)

$candidateFiles = @()
$candidateFiles += Invoke-GitLines -Repository $candidateRootFull -GitArgs @("-c", "core.quotepath=false", "ls-files")
$candidateFiles += Invoke-GitLines -Repository $candidateRootFull -GitArgs @("-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard")
$candidateFiles = @($candidateFiles | ForEach-Object { $_.Trim().Replace("\", "/") } | Where-Object { $_ } | Sort-Object -Unique)

$forbiddenPaths = @($candidateFiles | Where-Object { Test-ForbiddenReleasePath -RelativePath $_ })

$credentialInventory = Read-CredentialInventory -Paths $CredentialEnvironmentFiles
$credentialValues = $credentialInventory.Values

$binaryExtensions = @(
    ".woff", ".woff2", ".ttf", ".otf", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".zip", ".gz", ".tgz", ".7z", ".exe", ".dll", ".bin"
)
$secretMatchPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$conflictMarkerPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$skippedLargeCount = 0

foreach ($relativePath in $candidateFiles) {
    $fullPath = [IO.Path]::GetFullPath((Join-Path $candidateRootFull $relativePath))
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }
    $file = Get-Item -LiteralPath $fullPath
    if ($file.Length -gt $MaximumTextFileBytes) {
        $skippedLargeCount++
        continue
    }
    if ($binaryExtensions -contains $file.Extension.ToLowerInvariant()) { continue }

    try { $content = [IO.File]::ReadAllText($fullPath) } catch { continue }
    if ($content -match "(?m)^(<<<<<<<|=======|>>>>>>>)") {
        [void]$conflictMarkerPaths.Add($relativePath)
    }
    foreach ($value in $credentialValues) {
        if ($content.IndexOf($value, [StringComparison]::Ordinal) -ge 0) {
            [void]$secretMatchPaths.Add($relativePath)
            break
        }
    }
}

$baselineCommit = [string](Invoke-GitLines -Repository $candidateRootFull -GitArgs @("rev-parse", "--verify", "${OutgoingBaseline}^{commit}") | Select-Object -First 1)
& git -C $candidateRootFull merge-base --is-ancestor $baselineCommit HEAD
if ($LASTEXITCODE -ne 0) { throw "Outgoing baseline is not an ancestor of HEAD" }

$outgoingObjectLines = Invoke-GitLines -Repository $candidateRootFull -GitArgs @("-c", "core.quotepath=false", "rev-list", "--objects", "${baselineCommit}..HEAD")
$outgoingObjectPaths = @{}
$outgoingObjectIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($line in $outgoingObjectLines) {
    if ($line -notmatch "^([0-9a-fA-F]{40,64})(?:\s+(.*))?$") { continue }
    $objectId = $matches[1].ToLowerInvariant()
    [void]$outgoingObjectIds.Add($objectId)
    if ($matches.Count -gt 2 -and $matches[2]) { $outgoingObjectPaths[$objectId] = $matches[2].Replace("\", "/") }
}

$outgoingMetadata = @()
if ($outgoingObjectIds.Count -gt 0) {
    $outgoingMetadata = @($outgoingObjectIds | & git -C $candidateRootFull cat-file "--batch-check=%(objectname) %(objecttype) %(objectsize)")
    if ($LASTEXITCODE -ne 0) { throw "git cat-file metadata scan failed" }
}
$outgoingBlobCount = 0
$outgoingScannedBlobCount = 0
$outgoingSkippedLargeBlobCount = 0
$outgoingSecretMatchPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($metadata in $outgoingMetadata) {
    if ($metadata -notmatch "^([0-9a-fA-F]{40,64})\s+blob\s+(\d+)$") { continue }
    $objectId = $matches[1].ToLowerInvariant()
    $objectSize = [int64]$matches[2]
    $outgoingBlobCount++
    if ($objectSize -gt $MaximumTextFileBytes) {
        $outgoingSkippedLargeBlobCount++
        continue
    }
    $outgoingScannedBlobCount++
    $content = Read-GitBlobText -Repository $candidateRootFull -ObjectId $objectId
    foreach ($value in $credentialValues) {
        if ($content.IndexOf($value, [StringComparison]::Ordinal) -lt 0) { continue }
        $displayPath = if ($outgoingObjectPaths.ContainsKey($objectId)) { [string]$outgoingObjectPaths[$objectId] } else { "blob:$($objectId.Substring(0, 12))" }
        [void]$outgoingSecretMatchPaths.Add($displayPath)
        break
    }
}

$diffCheck = @(& git -C $candidateRootFull diff --check)
$diffCheckPassed = ($LASTEXITCODE -eq 0)

$result = [pscustomobject]@{
    CandidateRoot = $candidateRootFull
    CandidateFileCount = $candidateFiles.Count
    CredentialEnvironmentFileCount = $credentialInventory.EnvironmentFileCount
    CredentialCandidateCount = $credentialInventory.CandidateCount
    CredentialValueCount = $credentialValues.Count
    SecretMatchCount = $secretMatchPaths.Count
    SecretMatchPaths = @($secretMatchPaths | Sort-Object)
    ForbiddenPathCount = $forbiddenPaths.Count
    ForbiddenPaths = $forbiddenPaths
    ConflictMarkerCount = $conflictMarkerPaths.Count
    ConflictMarkerPaths = @($conflictMarkerPaths | Sort-Object)
    SkippedLargeFileCount = $skippedLargeCount
    OutgoingBaseline = $baselineCommit
    OutgoingBlobCount = $outgoingBlobCount
    OutgoingScannedBlobCount = $outgoingScannedBlobCount
    OutgoingSkippedLargeBlobCount = $outgoingSkippedLargeBlobCount
    OutgoingSecretMatchCount = $outgoingSecretMatchPaths.Count
    OutgoingSecretMatchPaths = @($outgoingSecretMatchPaths | Sort-Object)
    DiffCheck = if ($diffCheckPassed) { "passed" } else { "failed" }
}
$result | ConvertTo-Json -Depth 4

if ($secretMatchPaths.Count -gt 0 -or $outgoingSecretMatchPaths.Count -gt 0 -or $forbiddenPaths.Count -gt 0 -or $conflictMarkerPaths.Count -gt 0 -or -not $diffCheckPassed) {
    throw "Release candidate safety checks failed. Only counts and matched paths were emitted; credential values were never printed."
}
