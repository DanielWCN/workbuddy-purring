# 部署指南

## 方案对比

| 方案 | 不开机 | 难度 | 依赖 | 适合 |
|---|---|---|---|---|
| A. 金山 AirScript | ✅ 是 | 低（一次性 5 分钟） | 金山文档账号 | 主推，真·无人值守 |
| B. 本地 Windows 定时 | ❌ 需开过机 | 低 | Windows + Python | 补充，登录即触发 |
| C. 云端 Python | ✅ 是 | 中（需云环境） | 任意云函数/服务器 | 有云资源的用户 |

建议 A 为主、B 为补充，形成双保险。

## 方案 A：金山文档 AirScript（主推）

1. 打开 `kdocs.cn`，微信扫码登录，新建 **智能表格**（不是普通表格）。
2. 把你自己的 `refreshToken` 粘贴到 **B1**（获取方法见 `token-guide.md`）。
3. 顶部菜单 → **效率 → 高级开发 → AirScript 脚本编辑器** → 新建脚本 → 粘贴 `scripts/wps_airscript.js` 全部内容 → 保存。
4. 编辑器工具栏 → **服务 → 添加服务 → 勾选「网络 API」**。
   - ⚠️ 不勾这步，`HTTP` 对象不存在，脚本会报错。
5. 点「运行」试跑：会自动建「WorkBuddy签到」工作表，B5~B8 出现结论；看到 `✅` 即成功。
6. **效率 → 高级开发 → 定时任务 → 新建**：选该脚本，设每天 09:00；建议再加 21:00 兜底（脚本幂等，不会重复领）。

要点：
- 结果写入是**覆盖** B5~B10 固定单元格，不新增行、不累积 log。
- B1 每次运行自动换新并回写，永久有效。
- 金山编辑器自带的「运行记录」是平台功能，不在你的表格里。

## 方案 B：本地 Windows

1. 确保 Python 3 可用（在 PATH 中），WorkBuddy 已登录。
2. 立即跑一次：`python scripts/checkin.py --verbose`
3. 首次会提取并缓存凭证到 `config/token_state.json`。
4. 静默自启动：把 `scripts/run_silent.vbs` 的**快捷方式**放进
   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`。
   - 解释器默认用系统 `python`；如需指定，设环境变量 `WORKBUDDY_PY`。
5. 若需每天固定时刻运行，用 Windows 任务计划程序调用 `checkin.py`（需管理员权限）。

## 方案 C：云端 Python

适用于云函数、服务器 cron、GitHub Actions 等能跑 Python 且能持久化文件的环境。

```bash
export WORKBUDDY_REFRESH_TOKEN="你的refreshToken"
export WORKBUDDY_STATE_FILE="/持久目录/cloud_state.json"
python scripts/cloud_checkin.py
```

- `WORKBUDDY_STATE_FILE` 必须在**持久目录**：每次运行会把新 refreshToken 写回，否则 30 天后失效。
- `WORKBUDDY_UID` 通常不用填（脚本从 token 自动解析）。
- GitHub Actions 等无持久磁盘的环境，需把新 token 写回 Secrets 或用其他持久化手段。

## 验证是否成功

- 金山/云端：看表格 B5=签到结论、B6=猫猫结论、B7=整体、B8=时间。
- 本地：看命令行 JSON 输出的 `status`，或 `logs/checkin.log`。
- 微信（若配置）：见 `wechat-push.md`。

`already_signed` / `traveling` / `daily_limit_reached` 都是**正常状态**，不是错误。
