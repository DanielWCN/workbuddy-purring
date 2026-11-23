# Changelog

本文件记录 workbuddy-purring 的重要变更。

## [1.0.0] — 2026-11-23

首个公开版本（原名 `checkin-buddy`，为统一命名体系改为 `workbuddy-purring`）。

### 新增

- **金山文档 AirScript 云端版**（`scripts/wps_airscript.js`）—— 服务端定时任务，真·不开机
  - `refreshToken` 自动续期并回写表格 B1，长期有效
  - 签到状态预查 + 幂等领取，重复运行不重复领奖
  - 猫猫"先领奖、再派出"逻辑，避免行程到期作废
  - 结果写入固定单元格并自动美化配色（成功绿 / 失败红）
  - 可选 Server酱微信推送（读取表格 B9 的 SendKey），推送失败不影响主流程
- **本地 Windows 版**（`scripts/checkin.py` + `scripts/run_silent.vbs`）
  - `token_core.py` 三级凭证兜底：缓存续期 → 内存反查密钥解密 → 内存明文 JWT
  - AES-256-GCM 解密登录态信封，零第三方依赖（仅用 Node 内置 crypto）
  - 启动文件夹 VBS 静默触发，不弹窗
- **通用云端 Python 版**（`scripts/cloud_checkin.py`）—— 任意云函数 / 服务器 cron
- WorkBuddy 技能定义 `SKILL.md`，符合 `agent_created: true` 规范，可上架专家技能

### 安全

- 仓库不含任何真实凭证或用户 ID：UID 从 token 的 JWT `sub` 字段自动解析
- `config/token_state.json`、`config/credentials.json`、`cloud_state.json` 已由 `.gitignore` 排除
- keyId 不写死，运行时按 `sha256(key)[:16]` 在内存候选中反查
