# Exporta la presentación a PDF con PowerPoint (fuentes reales) sin mostrar ventanas.
param([string]$pptx = "$PSScriptRoot\..\CinnaParleys_UML.pptx")
$pptx = (Resolve-Path $pptx).Path
$pdf = [System.IO.Path]::ChangeExtension($pptx, ".pdf")
$pp = New-Object -ComObject PowerPoint.Application
try {
  $pres = $pp.Presentations.Open($pptx, $true, $false, $false)
  $pres.SaveAs($pdf, 32)
  $pres.Close()
} finally {
  $pp.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
Write-Output "pdf: $pdf"
