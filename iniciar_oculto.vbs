' Arranca CinnaParleys SIN ventanas de terminal (API + interfaz) y abre el navegador cuando esté listo.
' Lo que escriben los servidores queda en data\api.log y data\web.log. Para apagarlo: detener.bat
Option Explicit
Dim sh, fso, dir, http, i, listo
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(dir & "\.venv\Scripts\python.exe") Then
  MsgBox "No encuentro el entorno de Python (.venv). Ejecuta instalar.bat primero.", 48, "CinnaParleys"
  WScript.Quit 1
End If

sh.CurrentDirectory = dir
' 0 = ventana oculta; la consola oculta la heredan también sus subprocesos (no aparece ninguna terminal)
sh.Run "cmd /c "".venv\Scripts\python.exe -m uvicorn api.main:app --app-dir . --host 127.0.0.1 --port 8765 > data\api.log 2>&1""", 0, False
sh.Run "cmd /c ""web\arrancar_web.cmd > data\web.log 2>&1""", 0, False

' espera a que la interfaz responda (si hay que recompilarla tarda ~1 minuto)
listo = False
For i = 1 To 120
  WScript.Sleep 2000
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP")
  http.Open "GET", "http://localhost:3100", False
  http.Send
  If Err.Number = 0 Then
    If http.Status = 200 Then listo = True
  End If
  Err.Clear
  On Error GoTo 0
  If listo Then Exit For
Next

sh.Run "http://localhost:3100"
