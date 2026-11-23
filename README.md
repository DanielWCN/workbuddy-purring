<div align="center">

# WorkBuddy Purring

**WorkBuddy 每日自动签到 · 猫猫旅行自动化**

> *Purring* — 猫的呼噜声，也是服务器持续运转的低鸣。
> 你的猫猫在云端一直呼噜着，替你把每一天的签到做完。

不开机也能签到 —— 云端定时、零成本、凭证自动续期

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Skill](https://img.shields.io/badge/WorkBuddy%20Skill-compatible-7c3aed.svg)](SKILL.md)

[English](#english) · [快速开始](#快速开始推荐金山云端不开机) · [工作原理](#工作原理) · [FAQ](#faq)

</div>

---

## 这是什么

WorkBuddy 客户端每天可以签到领积分、派"猫猫"出去旅行领奖励。默认你得**打开客户端、点几下**，一天不点就断签。

`workbuddy-purring` 把这件事完全自动化：

- **真·不开机** —— 签到逻辑托管在金山文档的服务端定时任务里，电脑关机、客户端没开，照样签到
- **一次配置，长期有效** —— 每次运行自动用 `refreshToken` 换新 token 并写回，长期滚动续期，不用反复登录
- **零成本** —— 用免费的金山文档 + 免费 Server酱，无需服务器、无需域名、无需付费云函数
- **猫猫不漏奖** —— 到家先领礼物再派新一趟，避免行程作废
- **可选推微信** —— 每天一条消息告诉你"签到了多少分、猫猫在哪"
- **表格自动美化** —— 结果按成功/失败自动上色，手机上看一眼就懂

> ⚠️ 本项目通过 WorkBuddy 官方接口实现自动化，属于非官方工具。使用即表示你理解并自行承担与 WorkBuddy 服务条款相关的责任。`refreshToken` 等同账号密码，请务必保密。

## 30 秒看懂

| | |
|---|---|
| **要装什么** | 金山文档账号（免费）+ 一个 WorkBuddy 账号 |
| **要会写代码吗** | 不需要，只粘贴一段脚本 |
| **要一直开电脑吗** | 不需要 |
| **一天花多少钱** | 0 元 |
| **每天收到几条微信** | 0 或 1 条（可选） |

## 快速开始（推荐：金山云端，不开机）

```
① 金山文档新建「智能表格」
② 把你的 refreshToken 粘到 B1 格子
③ 效率 → 高级开发 → AirScript 脚本编辑器，粘贴 scripts/wps_airscript.js
④ 服务 → 添加服务 → 勾选「网络 API」（关键，否则 HTTP 对象不存在）
⑤ 点「运行」试跑，B5 出现 ✅ 即成功
⑥ 效率 → 高级开发 → 定时任务 → 每天 09:00
```

刷新 token 获取方法见 [凭证指南](references/token-guide.md)。
每一步的详细说明见 [部署指南](references/deploy-guide.md)。

### 表格单元格约定

| 单元格 | 内容 |
|---|---|
| `B1` | 你的 refreshToken（脚本自动换新并回写，**不要删**） |
| `B3` | 接口地址 |
| `B5` | 签到结论（✅/❌ + 连签天数 + 累计积分） |
| `B6` | 猫猫结论（已到家 / 旅行中 / 今日名额已用） |
| `B7` | 整体结果 |
| `B8` | 上次运行时间（北京时区） |
| `B9` | 微信 SendKey（可选，不填就不推送） |
| `B10` | 微信推送结果 |

**结果写入为覆盖固定单元格，每天覆盖一次，不累积历史行** —— 手机上永远只有"今天这一份"。

## 其他部署方式

| 方式 | 适合谁 | 需要开机吗 |
|---|---|---|
| **金山文档 AirScript**（主推） | 大多数人 | ❌ 不需要 |
| **本地 Windows**（`checkin.py` + 启动文件夹 VBS） | 愿意开机顺便跑 | ✅ 登录时触发 |
| **任意云函数 / 服务器 cron**（`cloud_checkin.py`） | 有自己的机器 | ❌ 不需要 |

本地方案跑一次会从客户端内存自动提取并缓存凭证，之后靠缓存续期即可。

```bash
python scripts/checkin.py --verbose     # 立即签到一次
python scripts/token_core.py --force --json   # 只导出 refreshToken
```

云端 Python 方案设置两个环境变量即可：

```bash
export WORKBUDDY_REFRESH_TOKEN="<你的 refreshToken>"
export WORKBUDDY_STATE_FILE="/持久目录/cloud_state.json"
python scripts/cloud_checkin.py
```

## 工作原理

```
┌─────────────────────────────────────────────┐
│  金山文档服务端定时任务（每天 09:00）          │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
       ① POST /v2/plugin/auth/token/refresh
          用 B1 的 refreshToken 换新 accessToken
          └─► 新 refreshToken 写回 B1（自动续期）
                   │
                   ▼
       ② POST /v2/billing/meter/checkin-activity-status
          先查今日状态（幂等，避免重复领取）
                   │
                   ▼
       ③ POST /v2/billing/meter/daily-checkin
          领取今日签到积分
                   │
                   ▼
       ④ GET  /activity/growth/buddy/travel/status
          猫猫状态：idle / traveling / arrived
          └─► arrived → POST .../travel/claim（先领奖）
          └─► idle    → POST .../travel/depart（再派出）
                   │
                   ▼
       ⑤ 写入 B5~B8，自动美化配色
          └─► 可选：Server酱推送到微信「方糖」服务号
```

三条设计原则：

1. **幂等** —— 重复运行不会重复领奖，一天跑 3 次和跑 1 次结果一样
2. **不写死任何用户身份** —— UID 从 token 的 JWT `sub` 字段自动解析，谁用都能自动识别
3. **失败不扩散** —— 推送失败、样式美化失败都被容错包住，绝不影响签到主流程

## 微信推送（可选）

在 [sct.ftqq.com](https://sct.ftqq.com) 微信扫码登录，复制页面上的 **SendKey**，填进表格 `B9` 即可。

- 免费 5 条/天、免实名认证（对比 PushPlus 需实名）
- 消息由微信 **「方糖」服务号** 发出 → 微信「通讯录 → 服务号 → 方糖」
- 它藏在"服务号"文件夹里，**不会像好友消息那样弹窗**，记得主动点进去看
- 首次需在扫码登录时关注并绑定「方糖」，否则收不到

详见 [微信推送说明](references/wechat-push.md)。

## 目录结构

```
workbuddy-purring/
├── SKILL.md                      WorkBuddy 技能定义（可上架专家技能）
├── README.md
├── CHANGELOG.md
├── LICENSE
├── scripts/
│   ├── wps_airscript.js          ★ 金山云端版（主推：签到+派猫+推送+美化）
│   ├── token_core.py             凭证核心：提取/解密/续期（Windows，零依赖）
│   ├── checkin.py                本地主脚本（签到 + 派猫 + 日志）
│   ├── cloud_checkin.py          通用云端 Python 版
│   └── run_silent.vbs            Windows 静默启动器（登录时触发）
├── config/
│   └── credentials.example.json  环境变量示例
└── references/
    ├── token-guide.md            凭证获取与续期原理
    ├── deploy-guide.md           三种部署方式逐步说明
    ├── wechat-push.md            微信推送配置与消息查看
    └── api-notes.md              接口清单与逆向事实（供维护者）
```

## 安全

- `refreshToken`、`config/token_state.json`、`cloud_state.json` = **账号钥匙**，绝不提交公开仓库（`.gitignore` 已排除）
- 仓库**不包含任何真实凭证或用户 ID**：UID 从 JWT 自动解析，示例配置只有占位符
- 所有日志与输出中 token 均脱敏或不打印
- 金山表格权限请设为「仅自己可见」，不要分享链接
- 如果你 fork 了本仓库，**请先确认 `config/` 下没有自己的 token 文件**

## FAQ

**Q：会封号吗？**
本项目调用的是 WorkBuddy 自己的正常接口，行为和手动点击客户端一致。但它是非官方工具，是否违反服务条款由你自行判断；请不要高频刷接口。

**Q：猫猫一天能派多次吗？**
不能。接口限制每日 1 次，脚本已实测确认。行程 1~4 小时、奖励 5~10 积分。

**Q：猫猫的礼物会作废吗？**
会 —— 到家后必须领取，逾期作废。脚本按"先领后派"顺序处理，不会漏。

**Q：金山表格要设置成公开吗？**
不要。设「仅自己可见」，因为 B1 里有你的 refreshToken。

**Q：为什么每次都要刷新 token？**
refreshToken 约 30 天有效，但每次 refresh 都会返回新的 refreshToken。脚本每次运行都换新并写回 B1，等于滚动续期，可以一直用下去。

**Q：升级了 WorkBuddy 客户端还能用吗？**
接口路径集中在各脚本顶部常量，路径变了改一处即可。解密用的 keyId 会随大版本变化，`token_core.py` 会自动在内存中反查；万一失败可用 `WORKBUDDY_KEY_ID` 手动指定。

**Q：WorkBuddy 专家技能里怎么装？**
`SKILL.md` 已符合 WorkBuddy 技能规范（`agent_created: true`），把整个目录作为技能包安装即可。

## License

MIT © DanielWCN

---

## English

**workbuddy-purring** automates WorkBuddy's daily check-in (earn credits) and buddy-cat travel rewards.

- ☁️ **Truly headless** — the script runs on Kingsoft/WPS Docs' server-side scheduler, so it keeps working when your PC is off
- 🔄 **Self-renewing credentials** — every run refreshes and writes back the token, so it keeps working indefinitely
- 💸 **Free** — free Kingsoft Docs + free Server酱 (no paid cloud functions, no server)
- 🐱 **Never misses a reward** — claims the arrived gift before dispatching the next trip
- 💬 **Optional WeChat push** — one message per day with your streak and the cat's status

Quick start: create a Kingsoft Docs sheet → paste your `refreshToken` into cell `B1` → paste [`scripts/wps_airscript.js`](scripts/wps_airscript.js) into the AirScript editor → enable the **网络 API / Network API** service → run once → set a daily scheduled task.

⚠️ Unofficial tool. `refreshToken` is equivalent to your password — never commit or share it.

MIT License
