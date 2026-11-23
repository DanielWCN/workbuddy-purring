# 接口清单与逆向事实（供维护者）

> 逆向自 WorkBuddy 桌面端 v5.9.3 程序包，并在本机实测 HTTP 200。接口若随版本变更，改各脚本顶部常量即可。

## 服务地址

`https://copilot.tencent.com`

## 鉴权头模式

```
Authorization: Bearer <accessToken>
X-User-Id: <用户ID，从 accessToken 的 JWT sub 解析>
X-Domain: www.workbuddy.cn
X-Product-Code: workbuddy
```

业务接口需带 `X-Product-Code: workbuddy`。

## 凭证接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v2/plugin/auth/token/refresh` | 用 refreshToken 换新 accessToken + refreshToken |

请求头：`X-Refresh-Token: <rt>`、`X-Auth-Refresh-Source: plugin`、`X-Domain`、`Content-Type: application/json`，body `{}`。返回 `data.accessToken` / `data.refreshToken`。

## 签到接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v2/billing/meter/checkin-activity-status` | 查今日状态 |
| POST | `/v2/billing/meter/daily-checkin` | 领取签到积分（幂等） |

状态返回 `data.today_checked_in`、`streak_days`、`total_credits`。今日已签返回 `code=10001` 或 msg 含"已签"——正常，非错误。

## 猫猫旅行接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/activity/growth/buddy/travel/status` | 查旅行状态 |
| POST | `/activity/growth/buddy/travel/depart` | 派出，body `{"location_id": 1}` |
| POST | `/activity/growth/buddy/travel/claim` | 领旅行礼物 |

状态 `data.state`：`idle` / `traveling` / `arrived`；`daily_limit_reached` 表示今日名额用完。

**规则**：每日派 1 次、行程 1~4 小时、奖励 5~10 积分；猫到家后须在下次派之前领取，否则作废。因此脚本按"先领已到家的礼物，再派新一趟"处理。

## 登录态加密信封（Windows）

登录态文件：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`

- token 字段为 `auth.<field>.envelope`，base64 编码的 JSON，含 `suite=1`、`keyId`、`nonce`、`authTag`、`ciphertext`。
- 加密方式：AES-256-GCM，framing=`field`。
- 密钥 = `sha256(atRestSecretKey)`（atRestSecretKey 为 base64 字符串，运行时注入客户端进程内存）。
- `keyId = sha256(key).hexdigest()[:16]`，用于在内存候选里反查 atRestSecretKey（每台机器不同）。
- AAD 构造：`WB-AAD\0` + `\x01` + lp("WBEV1") + lp("sym-v1") + u32(suite) + lp(keyId) + [02 00 00]（framing=field 时）。
  - `lp(s)` = 4 字节大端长度 + UTF-8 字节。
- 解密用 Node 内置 crypto（`aes-256-gcm`），零第三方依赖。

## 兼容性

- 金山 AirScript：同时兼容 2.0（ET JSAPI，`Application.Sheets/Range`）与 1.0（databook），运行时自动探测。
- AirScript 不支持 `async/await`，全部用同步 `HTTP.fetch`；域名不能带端口/IP；单次超时上限约 60s。
- `keyId`、AAD 常量在大版本升级后可能变化，用 `token_core.py --force --json` 验证解密是否仍成功。
