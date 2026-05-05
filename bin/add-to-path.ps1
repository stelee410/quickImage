# Helper to add D:\dev\quickImage\bin to the User PATH so `sd` is available in new terminals.
# Idempotent — safe to run multiple times.

$target = 'D:\dev\quickImage\bin'
$current = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $current) { $current = '' }

$paths = $current -split ';' | Where-Object { $_ -ne '' }
if ($paths -contains $target) {
    Write-Output "PATH already contains: $target"
} else {
    $new = if ($current.TrimEnd(';') -eq '') { $target } else { ($current.TrimEnd(';')) + ';' + $target }
    [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    Write-Output "Added to User PATH: $target"
    Write-Output "Open a new terminal for the change to take effect."
}
