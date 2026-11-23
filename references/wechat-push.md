# 微信推送配置

## 原理

签到脚本用 Server酱（ServerChan）把结果推到微信：脚本 → HTTP POST → Server酱服务器 → 微信「方糖」服务号模板消息。

选 Server酱而非 PushPlus 的原因：Server酱免费 5 条/天且**免实名认证**；PushPlus 现在发消息强制实名，不满足零门槛要求。

## 配置步骤

1. 打开 `sct.ftqq.com`，**微信扫码登录**。
2. 按提示关注并绑定「方糖」服务号、完成消息通道配置。
3. 在「SendKey」页面复制密钥（`SCT` 开头的一串字符）。
4. 把 SendKey 填进金山表格 **B9**（A9 标签脚本会自动建好）。
5. 保存。下次定时运行即会推送。

留空 B9 = 不推送，签到照常。推送失败也**绝不影响**已写好的签到结果（B5~B8）。推送结果写入 B10，便于排查。

## 消息在哪看、谁发来的

- 消息由微信里的 **「方糖」服务号** 发出，不是好友消息。
- 查看路径：微信 → 通讯录 → 公众号/服务号 → **方糖**。
- 它藏在「服务号」文件夹里，**不会像好友消息那样弹出**，只有小红点，需主动点进去。
- 首次必须在 sct.ftqq.com 扫码登录时关注并绑定「方糖」，否则收不到。

## 立即验证

在 `sct.ftqq.com` 页面点「发送测试」，或执行：

```bash
curl -X POST "https://sctapi.ftqq.com/你的SENDKEY.send" -d "title=测试" -d "desp=WorkBuddy 推送测试"
```

微信当场收到即打通。返回 JSON 中 `code` 为 0 表示服务端受理。

## 接口细节（维护者）

- 标准 SendKey：`POST https://sctapi.ftqq.com/{SendKey}.send`，JSON body `{"title": ..., "desp": ...}`，HTTP 200 且 `code=0` 为成功。
- `sctp` 开头的 SendKey（Server酱³）：`POST https://{uid}.push.ft07.com/send/{SendKey}.send`，其中 uid 是 `sctp` 与 `t` 之间的数字。
- 免费额度 5 条/天、每分钟上限 50 条；一天推 1 条足够。
- SendKey 等同推送凭证，泄露后任何人都能给你发消息，不要提交公开仓库。
