[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$JobManifestPath,
    [Parameter(Mandatory = $true)][string]$ResultPath,
    [Parameter(Mandatory = $true)][string]$WordPidPath,
    [Parameter(Mandatory = $true)][string]$ProgressPath
)

$ErrorActionPreference = 'Stop'
$word = $null
$document = $null

function Get-Sha256([string]$Path) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $bytes = $algorithm.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Write-ProgressEvent([string]$EventName) {
    $line = ([DateTimeOffset]::Now.ToString('o') + ' ' + $EventName)
    [System.IO.File]::AppendAllText($ProgressPath, $line + [Environment]::NewLine)
}

try {
    $manifest = Get-Content -Raw -LiteralPath $JobManifestPath | ConvertFrom-Json
    $source = [System.IO.Path]::GetFullPath([string]$manifest.source_path)
    $outputDirectory = [System.IO.Path]::GetFullPath([string]$manifest.output_directory)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw 'Source DOCX does not exist.'
    }
    if ([System.IO.Path]::GetExtension($source).ToLowerInvariant() -ne '.docx') {
        throw 'Only DOCX source files are accepted.'
    }
    if ((Get-Sha256 $source) -ne ([string]$manifest.source_sha256).ToLowerInvariant()) {
        throw 'Source SHA-256 verification failed inside the Windows worker.'
    }
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $docxOutput = Join-Path $outputDirectory 'rendered.docx'
    $pdfOutput = Join-Path $outputDirectory 'rendered.pdf'
    [System.IO.File]::Copy($source, $docxOutput, $true)
    Write-ProgressEvent 'source_copied'

    $beforeWordIds = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    if ($beforeWordIds.Count -ne 0) {
        throw ('Worker refuses to start while unmanaged WINWORD processes exist: ' + ($beforeWordIds -join ','))
    }
    $word = New-Object -ComObject Word.Application
    Write-ProgressEvent 'word_created'
    Start-Sleep -Milliseconds 250
    $newWordProcesses = @(Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $beforeWordIds -notcontains $_.Id })
    if ($newWordProcesses.Count -ne 1) {
        throw 'Worker could not identify exactly one isolated WINWORD process.'
    }
    [System.IO.File]::WriteAllText($WordPidPath, [string]$newWordProcesses[0].Id)
    Write-ProgressEvent ('word_pid=' + [string]$newWordProcesses[0].Id)
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $word.Options.UpdateLinksAtOpen = $false
    $word.Options.SaveNormalPrompt = $false
    $wordVersion = [string]$word.Version
    Write-ProgressEvent ('word_configured=' + $wordVersion)
    $document = $word.Documents.Open($docxOutput, $false, $false, $false)
    Write-ProgressEvent 'document_opened'
    try { $document.Fields.Update() | Out-Null } catch { }
    Write-ProgressEvent 'fields_updated'
    $document.Repaginate()
    Write-ProgressEvent 'repaginated'
    $document.Save()
    Write-ProgressEvent 'docx_saved'
    $document.ExportAsFixedFormat($pdfOutput, 17, $false, 0, 0, 1, 999, 0, $true, $true, 1, $true, $true, $false)
    Write-ProgressEvent 'pdf_exported'
    $pageCount = $document.ComputeStatistics(2)
    if ((Get-Item -LiteralPath $pdfOutput).Length -le 0) {
        throw 'Word produced an empty PDF.'
    }
    $result = [ordered]@{
        status = 'DONE'
        renderer = 'word-com-v1'
        word_version = $wordVersion
        page_count = $pageCount
        artifacts = @(
            [ordered]@{ kind = 'docx'; path = $docxOutput; sha256 = Get-Sha256 $docxOutput },
            [ordered]@{ kind = 'pdf'; path = $pdfOutput; sha256 = Get-Sha256 $pdfOutput }
        )
    }
    $temporary = "$ResultPath.tmp"
    $result | ConvertTo-Json -Depth 8 -Compress | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -Force -LiteralPath $temporary -Destination $ResultPath
    Write-ProgressEvent 'result_written'
    $document.Close($false)
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    $document = $null
    $word.Quit()
    [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    $word = $null
}
catch {
    [ordered]@{ status = 'FAILED'; error = $_.Exception.Message } |
        ConvertTo-Json -Compress |
        Set-Content -LiteralPath $ResultPath -Encoding utf8
    Write-Error $_
    exit 1
}
finally {
    if ($null -ne $document) {
        try { $document.Close($false) } catch { }
        try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) } catch { }
    }
    if ($null -ne $word) {
        try { $word.Quit() } catch { }
        try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
