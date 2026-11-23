# 凭证（refreshToken）获取与续期

## 为什么需要 refreshToken

WorkBuddy 的签到接口需要 accessToken（有效期约 28 天）。accessToken 由 refreshToken（有效期约 30 天）换取。refresh 每次都会返回**新的 refreshToken**，因此只要定期刷新就能无限续期，无需重复登录。

## 如何导出自己的 refreshToken

桌面端 v5.9.3 起，登录态文件 `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info` 中的 token 是 AES-256-GCM 加密信封，不是明文，无法直接复制。有两种方式取得：

### 方式一：本地脚本自动提取（Windows）

直接运行本地方案，`token_core.py` 会：

1. 从 WorkBuddy 进程内存反查 `atRestSecretKey`（用 `keyId = sha256(key)[:16]` 校验候选）。
2. 用密钥解密登录态里的 refreshToken 信封。
3. 调 refresh 接口换取 accessToken + 新 refreshToken，并缓存到 `config/token_state.json`。

```bash
python scripts/token_core.py --force --json
```

输出的 JSON 中 `refreshToken` 字段即为所需凭证（**注意保密，不要外传**）。

前置：WorkBuddy 客户端已登录并在运行；系统有可用 Node（脚本会自动查找，或用 `NODE_EXE` 指定）。

### 方式二：从缓存文件读取

若之前已跑过本地脚本，可直接读 `config/token_state.json` 的 `refreshToken` 字段。

## 续期机制

`get_tokens()` 三级优先：

1. **缓存续期**（最快，无需客户端运行）：读 `token_state.json` 的 refreshToken → refresh → 写回新 token。
2. **内存解密**：反查密钥 → 解密登录态 → refresh。需客户端已登录运行。
3. **内存明文兜底**：直接扫进程内存里的 JWT。客户端正在使用时可用。

云端路径下，`cloud_checkin.py` 每次运行把新 refreshToken 写回 `WORKBUDDY_STATE_FILE`；金山路径下 `wps_airscript.js` 把新 token 写回表格 B1。

## 常见失败处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `所有取 token 路径均失败` | 客户端未登录，且缓存 token 已过期 | 打开 WorkBuddy 登录一次，再跑 `python token_core.py --force` |
| `refresh 返回 401/403` | refreshToken 已失效（超过 30 天未运行） | 客户端登录后 `--force` 重建缓存 |
| `找不到 Node` | 系统无 Node 且 WorkBuddy 内置版未被识别 | 安装 Node，或设 `NODE_EXE` 指向 node.exe |
| `未能反查到 atRestSecretKey` | 客户端未运行，或大版本升级后 keyId 变化 | 启动客户端登录；升级后可用 `WORKBUDDY_KEY_ID` 指定新 keyId |
| 云端 30 天后失效 | 状态文件未持久化，新 token 没写回 | 确认 `WORKBUDDY_STATE_FILE` 在持久目录且可写 |

## 安全

- `refreshToken` / `token_state.json` / `cloud_state.json` = 账号钥匙，**不要外传、不要提交公开仓库**。
- 所有日志与输出中 token 均脱敏或不打印。
- 金山表格权限设为「仅自己可见」，绝不分享。
