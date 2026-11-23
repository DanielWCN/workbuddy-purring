' WorkBuddy 自动签到 - 静默启动器（通用版，无任何硬编码个人路径）
' 用法：把本文件的快捷方式放到「启动」文件夹，登录后自动运行，不弹黑色窗口。
' 优先用系统 python；也支持通过环境变量 WORKBUDDY_PY 指定解释器路径。
Option Explicit
Dim ws, py, script, cmd, shell
Set ws = CreateObject("WScript.Shell")
Set shell = CreateObject("WScript.Shell")

' 脚本路径 = 本 VBS 所在目录下的 checkin.py（相对定位，换个机器也能用）
script = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1) & "\checkin.py"

' 解释器：环境变量 > python > py 启动器
py = shell.ExpandEnvironmentStrings("%WORKBUDDY_PY%")
If py = "%WORKBUDDY_PY%" Or py = "" Then py = "python"

cmd = """" & py & """ """ & script & """"
' 0 = 隐藏窗口, False = 不等待
ws.Run cmd, 0, False
