#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 云端签到脚本 —— 真·不开机
====================================
放到任意支持 Python 的云端定时环境（云函数 / AirScript / GitHub Actions / 服务器 cron）。
只需一个环境变量 WORKBUDDY_REFRESH_TOKEN，脚本每天自动：
  1) 用 refreshToken 换新 accessToken + 新 refreshToken（30天有效，每次刷新重置 → 永久）
  2) 签到（幂等）
  3) 派猫猫旅行（先领后派，幂等）

⚠️ 关键：refresh 每次返回的新 refreshToken 必须持久化回环境变量/存储，否则 30 天后失效。
   本脚本用本地状态文件 CLOUD_STATE_FILE 保存新 refreshToken；云端环境请将该文件放在
   持久化目录，或用云厂商的环境变量更新 API 写回。

环境变量：
  WORKBUDDY_REFRESH_TOKEN  (必填) 初始 refreshToken
  WORKBUDDY_STATE_FILE     (可选) 状态文件路径，默认脚本同目录 cloud_state.json
  WORKBUDDY_UID            (可选) 用户 ID
  WORKBUDDY_DOMAIN         (可选) 默认 www.workbuddy.cn
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://copilot.tencent.com"
REFRESH_PATH = "/v2/plugin/auth/token/refresh"
CHECKIN_STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
CHECKIN_CLAIM_PATH = "/v2/billing/meter/daily-checkin"
TRAVEL_STATUS_PATH = "/activity/growth/buddy/travel/status"
TRAVEL_DEPART_PATH = "/activity/growth/buddy/travel/depart"
TRAVEL_CLAIM_PATH = "/activity/growth/buddy/travel/claim"
DEFAULT_DOMAIN = "www.workbuddy.cn"


def uid_from_token(token):
    """从 JWT payload 解析用户 ID，避免写死账号。"""
    try:
        import base64 as _b64
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        p = json.loads(_b64.urlsafe_b64decode(seg))
        return p.get("sub") or p.get("userId") or p.get("uid") or ""
    except Exception:
        return ""


def bj_now():
    return (datetime.datetime.now(datetime.timezone.utc) +
            datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def is_ok(code, resp):
    if code != 200 or not isinstance(resp, dict):
        return False
    return "code" not in resp or resp.get("code") in (0, "0")


def refresh(rt, domain):
    h = {"Content-Type": "application/json", "X-Refresh-Token": rt,
         "X-Auth-Refresh-Source": "plugin", "X-Domain": domain,
         "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3"}
    req = urllib.request.Request(ENDPOINT + REFRESH_PATH, data=b"{}", method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if d.get("code") != 0 or not (d.get("data") or {}).get("accessToken"):
        raise RuntimeError("refresh 失败: code=%s msg=%s" % (d.get("code"), d.get("msg")))
    return d["data"]


def call_api(token, uid, domain, method, path, body=None):
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token,
               "Content-Type": "application/json", "X-User-Id": uid, "X-Domain": domain,
               "X-Product-Code": "workbuddy", "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ENDPOINT + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw}


def main():
    domain = os.environ.get("WORKBUDDY_DOMAIN", DEFAULT_DOMAIN)
    state_file = os.environ.get("WORKBUDDY_STATE_FILE",
                                os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_state.json"))
    rt = os.environ.get("WORKBUDDY_REFRESH_TOKEN", "").strip()
    try:
        if os.path.exists(state_file):
            saved = json.load(open(state_file, encoding="utf-8"))
            rt = saved.get("refreshToken") or rt
    except Exception:
        pass
    if not rt:
        print(json.dumps({"status": "error", "reason": "no_refresh_token",
                          "hint": "设置环境变量 WORKBUDDY_REFRESH_TOKEN"}, ensure_ascii=False))
        return 2

    result = {"date": bj_now(), "source": "cloud"}
    try:
        data = refresh(rt, domain)
    except Exception as e:
        print(json.dumps({"status": "error", "reason": "refresh", "message": str(e)}, ensure_ascii=False))
        return 3
    at = data["accessToken"]
    # 用户 ID：优先环境变量，否则从 JWT 自动解析（无需写死任何账号）
    uid = os.environ.get("WORKBUDDY_UID", "").strip() or uid_from_token(at)
    new_rt = data.get("refreshToken") or rt
    # 持久化新 refreshToken（云端必须写到持久存储）
    try:
        json.dump({"refreshToken": new_rt, "updatedAt": bj_now()},
                  open(state_file, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        result["state_write_warning"] = str(e)

    # 签到
    code, resp = call_api(at, uid, domain, "POST", CHECKIN_STATUS_PATH, {})
    if is_ok(code, resp) and (resp.get("data") or {}).get("today_checked_in"):
        result["checkin"] = "already_signed"
    else:
        cc, cr = call_api(at, uid, domain, "POST", CHECKIN_CLAIM_PATH, {})
        result["checkin"] = "success" if is_ok(cc, cr) else "failed:http=%s" % cc

    # 派猫
    code, resp = call_api(at, uid, domain, "GET", TRAVEL_STATUS_PATH)
    if is_ok(code, resp):
        d = resp.get("data", {}) or {}
        state, limit = d.get("state"), bool(d.get("daily_limit_reached"))
        tv = {"state_before": state}
        if state == "arrived":
            cc, cr = call_api(at, uid, domain, "POST", TRAVEL_CLAIM_PATH, {})
            tv["claim"] = "success" if is_ok(cc, cr) else "failed"
            c2, r2 = call_api(at, uid, domain, "GET", TRAVEL_STATUS_PATH)
            if is_ok(c2, r2):
                state, limit = (r2.get("data") or {}).get("state"), bool((r2.get("data") or {}).get("daily_limit_reached"))
        if state == "idle" and not limit:
            dc, dr = call_api(at, uid, domain, "POST", TRAVEL_DEPART_PATH, {"location_id": 1})
            tv["depart"] = "success" if is_ok(dc, dr) else "failed:http=%s" % dc
        elif state == "traveling":
            tv["skip"] = "traveling"
        elif limit:
            tv["skip"] = "daily_limit_reached"
        result["travel"] = tv
    else:
        result["travel"] = "status_failed:http=%s" % code

    result["status"] = "ok"
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
