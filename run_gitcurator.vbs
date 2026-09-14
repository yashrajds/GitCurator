Set WshShell = CreateObject("WScript.Shell")
strPath = "c:\Users\hp\OneDrive\Desktop\New folder\P Projects\GitCurator"
WshShell.CurrentDirectory = strPath
WshShell.Run "python -m uvicorn app:app --host 127.0.0.1 --port 8000", 0, False
WScript.Sleep 2000
WshShell.Run "cmd /c start http://127.0.0.1:8000", 0, False
