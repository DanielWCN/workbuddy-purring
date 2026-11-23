---
name: workbuddy-purring
description: Set up fully automatic WorkBuddy daily check-in, points collection, and buddy-cat travel with optional WeChat notification. Use when a user asks to auto check in WorkBuddy, earn daily credits without opening the computer, schedule cloud-side check-in, send the buddy cat on trips, push check-in results to WeChat, or set up the workbuddy-purring project. Supports a cloud-first path (Kingsoft/WPS AirScript) and a local Windows path.
agent_created: true
---

# WorkBuddy Purring · 自动签到

> GitHub: [DanielWCN/workbuddy-purring](https://github.com/DanielWCN/workbuddy-purring) · 项目代号 **workbuddy-purring**
>
> *Purring* — 猫的呼噜声，也是服务器持续运转的低鸣。猫猫在云端一直呼噜着，替你把每一天的签到做完。

## 一句话介绍

把 WorkBuddy 每天的"签到领积分"和"派猫猫旅行领奖"这两件小事完全自动化——**电脑不开机、客户端不打开也能签到**，且 `refreshToken` 自动滚动续期，长期有效、零成本。

## 用途

为 WorkBuddy 配置无人值守的每日签到、积分领取与"猫猫旅行"领奖，并可选把结果推送到微信。核心是让签到在**不开机、不开客户端**的情况下由云端定时任务执行，实现长期自动续期。

本技能只调用 WorkBuddy 官方接口，不收集或上传任何数据到第三方。

## 何时使用

当用户提出以下任一需求时使用本技能：

- 让 WorkBuddy 每天自动签到、自动领积分
- "不开机也能签到"、云端定时签到
- 自动派猫猫旅行、到家自动领礼物
- 把签到结果推送到微信
- 配置本地登录时静默签到

## 前置条件

- 一个已登录的 WorkBuddy 账号（桌面端 v5.9.3 或相近版本）
- 用户自己的 `refreshToken`（账号凭证，等同于密码，必须保密）
- 云端方案：金山文档/WPS 账号（免费）；本地方案：Windows + Python 3

## 两种部署路径

### 路径 A：云端定时（推荐，真·不开机）

用金山文档 AirScript 把签到脚本托管在服务端，由金山每天定时触发。

1. 让用户从 WorkBuddy 导出自己的 `refreshToken`（方法见 `references/token-guide.md`）。
2. 在金山文档新建「智能表格」，把 `refreshToken` 粘贴到 **B1**。
3. 进入「效率 → 高级开发 → AirScript 脚本编辑器」，新建脚本，粘贴 `scripts/wps_airscript.js` 全部内容并保存。
4. 在编辑器「服务」中勾选「网络 API」（否则 `HTTP` 对象不存在）。
5. 在「效率 → 高级开发 → 定时任务」设每天 09:00，可选再加 21:00 兜底（脚本幂等，重复运行不会重复领奖）。
6. 脚本每次运行会自动 `refresh` 并把新 `refreshToken` 写回 B1，实现永久有效，无需手动重取。

表格约定：B1=refreshToken；B3=接口地址；B5~B8=签到/猫猫/整体/时间结论；B9=微信 SendKey（可选）；B10=微信推送结果。结果写入为**覆盖**固定单元格，不累积历史行。

### 路径 B：本地定时（Windows，登录后触发）

1. 运行 `scripts/checkin.py` 立即签到一次：`python scripts/checkin.py --verbose`。
2. 首次运行会从客户端内存提取凭证并缓存到 `config/token_state.json`（保密）。
3. 把 `scripts/run_silent.vbs` 的快捷方式放入 Windows「启动」文件夹，实现登录后静默运行。
4. 需要固定时刻运行时，另行配置任务计划程序。

`token_core.py` 提供三级凭证兜底：缓存续期 → 内存反查密钥解密 → 内存明文 JWT。只要每天至少跑一次，`refreshToken` 就会滚动更新，长期有效。

### 云端 Python（备选，任意云函数/服务器 cron）

用 `scripts/cloud_checkin.py`，设置环境变量 `WORKBUDDY_REFRESH_TOKEN` 与持久化的 `WORKBUDDY_STATE_FILE`。详见 `references/deploy-guide.md`。

## 可选：微信推送

脚本内置 Server酱推送：用户在 `sct.ftqq.com` 微信扫码获取 SendKey（免费 5 条/天、免实名），填入金山表格 B9 即可。消息由微信「方糖」服务号发出，位于微信「服务号」文件夹。推送失败不影响签到主流程。详见 `references/wechat-push.md`。

## 重要约定

- **用户 ID 不写死**：所有脚本从 token 的 JWT payload（sub 字段）自动解析 UID，仅当自动解析失败时才用环境变量 `WORKBUDDY_UID` 覆盖。
- **凭证不进代码**：`refreshToken`、`token_state.json`、`cloud_state.json` 等同于账号钥匙，绝不提交到公开仓库，日志与输出中均脱敏。
- **keyId 每台机器不同**：`token_core.py` 默认从内存候选自动反查；失败时用环境变量 `WORKBUDDY_KEY_ID` 指定。
- **接口路径集中定义**在各脚本顶部常量，接口变更时改一处即可。

## 参考文件

- `references/token-guide.md` — 凭证导出/续期原理与常见失败处理
- `references/deploy-guide.md` — 三种部署方式的逐步说明
- `references/wechat-push.md` — 微信推送配置与消息查看
- `references/api-notes.md` — 接口清单与逆向事实（供维护者）
