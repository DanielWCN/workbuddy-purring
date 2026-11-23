#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 自动签到 + 派猫猫旅行 —— 主执行脚本（本地 / 通用 Python 环境）
=========================================================================
整合 token_core（自动取 token + 续期）+ 签到引擎（幂等签到 + 派猫）。
零第三方依赖，仅用 Python 标准库。

用法：
  python checkin.py                 # 签到 + 派猫（默认 all）
  python checkin.py --mode checkin  # 只签到
  python checkin.py --mode travel   # 只派猫
  python checkin.py --verbose       # 打印详细过程

退出码：0=成功/正常跳过, 2=取token失败, 3=签到失败, 4=派猫失败
"""
import argparse
import base64
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import token_core  # noqa: E402

ENDPOINT = "https://copilot.tencent.com"
CHECKIN_STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
CHECKIN_CLAIM_PATH = "/v2/billing/meter/daily-checkin"
TRAVEL_STATUS_PATH = "/activity/growth/buddy/travel/status"
TRAVEL_DEPART_PATH = "/activity/growth/buddy/travel/depart"
TRAVEL_CLAIM_PATH = "/activity/growth/buddy/travel/claim"

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(SKILL_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "checkin.log")
DOMAIN = token_core.DOMAIN
MAX_RETRIES = 2


def bj_now():
    return (datetime.datetime.now(datetime.timezone.utc) +
            datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def log(msg, verbose=True):
    line = "[%s] %s" % (bj_now(), msg)
    if verbose:
        print(line)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def parse_jwt(token):
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        return {}


def is_ok(code, resp):
    if code != 200 or not isinstance(resp, dict):
        return False
    if "code" not in resp:
        return True
    return resp.get("code") == 0 or resp.get("code") == "0"


def make_client(token):
    uid = os.environ.get("WORKBUDDY_UID", "").strip() or token_core.uid_from_token(token)

    def once(method, path, body=None):
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-User-Id": uid,
            "X-Domain": DOMAIN,
            "X-Product-Code": "workbuddy",
            "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3",
            "Referer": "https://www.workbuddy.cn/",
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(ENDPOINT + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.getcode(), json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace") if e.fp else ""
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"_raw": raw}
        except Exception as e:
            return -1, {"error": "request_failed: %s" % e}

    def call(method, path, body=None):
        code, resp = once(method, path, body)
        for _ in range(MAX_RETRIES):
            if not (code == -1 or (isinstance(code, int) and 500 <= code <= 599)):
                break
            time.sleep(1)
            code, resp = once(method, path, body)
        return code, resp
    return call


def do_checkin(call):
    code, resp = call("POST", CHECKIN_STATUS_PATH, {})
    if not is_ok(code, resp):
        cc, cr = call("POST", CHECKIN_CLAIM_PATH, {})
        if is_ok(cc, cr):
            d = cr.get("data", {}) or {}
            return {"status": "success", "uncertain": True,
                    "message": "状态查询失败但领取成功", "credit": d.get("credit")}
        return {"status": "error", "phase": "status", "http": code, "body": resp}
    data = resp.get("data", {}) or {}
    if data.get("today_checked_in"):
        return {"status": "already_signed", "message": "今日已签，跳过",
                "streak_days": data.get("streak_days"), "total_credits": data.get("total_credits")}
    cc, cr = call("POST", CHECKIN_CLAIM_PATH, {})
    if not is_ok(cc, cr):
        return {"status": "error", "phase": "claim", "http": cc, "body": cr}
    d = cr.get("data", {}) or {}
    return {"status": "success", "message": "签到成功",
            "credit": d.get("credit"), "streak_days": d.get("streak_days"),
            "total_credits": d.get("total_credits")}


def do_travel(call, location_id=1):
    code, resp = call("GET", TRAVEL_STATUS_PATH)
    if not is_ok(code, resp):
        cc, cr = call("POST", TRAVEL_CLAIM_PATH, {})
        return {"state_before": "unknown", "uncertain": True,
                "claim": "success" if is_ok(cc, cr) else "failed:http=%s" % cc}
    data = resp.get("data", {}) or {}
    state = data.get("state")
    limit = bool(data.get("daily_limit_reached"))
    out = {"state_before": state}

    if state == "arrived":
        cc, cr = call("POST", TRAVEL_CLAIM_PATH, {})
        out["claim"] = "success" if is_ok(cc, cr) else "failed:http=%s" % cc
        c2, r2 = call("GET", TRAVEL_STATUS_PATH)
        if is_ok(c2, r2):
            d2 = r2.get("data", {}) or {}
            state, limit = d2.get("state"), bool(d2.get("daily_limit_reached"))

    if state == "idle" and not limit:
        dc, dr = call("POST", TRAVEL_DEPART_PATH, {"location_id": location_id})
        out["depart"] = "success" if is_ok(dc, dr) else "failed:http=%s code=%s" % (dc, (dr or {}).get("code"))
        out["location_id"] = location_id
    elif state == "traveling":
        out["skip"] = "traveling"
    elif limit:
        out["skip"] = "daily_limit_reached"
    return out


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy 自动签到 + 派猫猫")
    ap.add_argument("--mode", choices=["all", "checkin", "travel"], default="all")
    ap.add_argument("--location-id", type=int, default=1)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--force-token", action="store_true", help="强制重新解密 token")
    a = ap.parse_args()

    log("=== 开始 (mode=%s) ===" % a.mode, a.verbose)
    try:
        t = token_core.get_tokens(force_refresh=a.force_token)
    except token_core.TokenError as e:
        log("取 token 失败: %s" % e, a.verbose)
        print(json.dumps({"status": "error", "reason": "token", "message": str(e)}, ensure_ascii=False))
        return 2
    at = t["accessToken"]
    payload = parse_jwt(at)
    days_left = round((payload.get("exp", 0) - time.time()) / 86400, 1)
    log("token 来源=%s 剩余%.1f天" % (t.get("source"), days_left), a.verbose)

    call = make_client(at)
    result = {"date": bj_now(), "mode": a.mode, "token_source": t.get("source"),
              "token_days_left": days_left}
    rc = 0
    if a.mode in ("all", "checkin"):
        r = do_checkin(call)
        result["checkin"] = r
        log("签到: %s" % r.get("message") or r.get("status"), a.verbose)
        if r.get("status") == "error":
            rc = 3
    if a.mode in ("all", "travel"):
        r = do_travel(call, a.location_id)
        result["travel"] = r
        log("派猫: %s" % json.dumps(r, ensure_ascii=False), a.verbose)
        if any(str(v).startswith("failed") for v in r.values() if isinstance(v, str)):
            rc = 4 if rc == 0 else rc
    result["status"] = "ok" if rc == 0 else "partial_error"
    log("=== 结束 status=%s ===" % result["status"], a.verbose)
    print(json.dumps(result, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
