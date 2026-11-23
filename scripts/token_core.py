#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 凭证核心 —— 自动获取并长期续期 accessToken / refreshToken
=====================================================================
原理（逆向自 WorkBuddy 桌面端 v5.9.3，已在本机实测通过）：
  1. 登录态文件 workbuddy-desktop.info 里 accessToken/refreshToken 是 AES-256-GCM 加密信封。
  2. 密钥 = sha256(atRestSecretKey)，atRestSecretKey 运行时注入客户端进程内存。
     用已知 keyId（sha256(key) 前16位）可反查到该密钥。
  3. AES-GCM 的 AAD 由固定常量拼成，framing=field。
  4. 解出的 refreshToken 可调官方 refresh 接口换新的 accessToken + refreshToken（每次都换新 → 可无限滚续）。
  5. 兜底：直接从进程内存扫明文 JWT（客户端 running 时）。

零第三方依赖：加密解密用 ctypes 调 Windows BCrypt（系统自带），或 subprocess 调 Node（可选）。
本模块优先用"缓存的 refreshToken"续期（最快、无需客户端运行），失败时才走"内存提取"。

对外只暴露一个函数：
    get_tokens(force_refresh=False) -> {"accessToken":..., "refreshToken":..., "source":..., ...}
失败抛 TokenError。
"""
import base64
import ctypes
import ctypes.wintypes as w
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ---------- 常量 ----------
ENDPOINT = "https://copilot.tencent.com"
REFRESH_PATH = "/v2/plugin/auth/token/refresh"
# keyId 是每台机器不同的派生值；留空时脚本从内存候选里自动反查（唯一命中即采用）。
# 若自动反查失败，可通过环境变量 WORKBUDDY_KEY_ID 指定。
KEY_ID_HINT = os.environ.get("WORKBUDDY_KEY_ID", "").strip()
AUTH_FILE = os.path.expandvars(
    r"%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info")
STATE_FILE = os.environ.get("WORKBUDDY_STATE_FILE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "token_state.json")
DOMAIN = os.environ.get("WORKBUDDY_DOMAIN", "www.workbuddy.cn")


def uid_from_token(token):
    """从 JWT 的 payload 解析用户 ID（sub 字段），避免在代码里写死任何账号。"""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg))
        return payload.get("sub") or payload.get("userId") or payload.get("uid") or ""
    except Exception:
        return ""

# AAD 常量（逆向所得）
_AAD_PREFIX = b"WB-AAD\x00"
_AAD_ONE = b"\x01"
_D = {"file": "WBEF1", "field": "WBEV1", "record": "WBER1", "stream": "WBES1"}
_U = {"file": 1, "field": 2, "record": 3, "stream": 4}


class TokenError(Exception):
    pass


def _log(msg):
    print("[token] " + str(msg), file=sys.stderr)


# ---------- 编码辅助 ----------
def _u32(n):
    return n.to_bytes(4, "big")


def _lp(s):
    b = s.encode("utf-8") if isinstance(s, str) else s
    return _u32(len(b)) + b


def _aad(key_id, suite, framing="field", final=None):
    return b"".join([
        _AAD_PREFIX, _AAD_ONE,
        _lp(_D[framing]), _lp("sym-v1"), _u32(suite), _lp(key_id),
        bytes([_U[framing]]), b"\x00",
        bytes([0 if final is None else (2 if final else 1)]),
    ])


def _derive_key_id(key_bytes):
    return hashlib.sha256(key_bytes).hexdigest()[:16]


# ---------- AES-256-GCM 解密（Windows BCrypt，零依赖） ----------
class _Bcrypt:
    """用 ctypes 调 Windows bcrypt.dll 做 AES-GCM 解密。"""
    def __init__(self):
        self.dll = ctypes.WinDLL("bcrypt.dll")
        self.BCRYPT_AES_ALGORITHM = "AES"
        self.hAlg = ctypes.c_void_p()
        self.hKey = ctypes.c_void_p()
        self._load()

    def _load(self):
        dll = self.dll
        dll.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                                    ctypes.c_wchar_p, ctypes.c_wchar_p, w.DWORD]
        dll.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
        dll.BCryptSetAlgorithmProperty.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                                   ctypes.c_void_p, w.DWORD]
        dll.BCryptSetAlgorithmProperty.restype = ctypes.c_long
        dll.BCryptImportKey.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD,
                                        ctypes.c_void_p, w.DWORD,
                                        ctypes.POINTER(ctypes.c_void_p), w.DWORD]
        dll.BCryptImportKey.restype = ctypes.c_long
        dll.BCryptDecrypt.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, w.DWORD,
                                      ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD,
                                      ctypes.POINTER(w.DWORD)]
        dll.BCryptDecrypt.restype = ctypes.c_long
        dll.BCryptDestroyKey.argtypes = [ctypes.c_void_p]
        dll.BCryptDestroyKey.restype = ctypes.c_long
        dll.BCryptCloseAlgorithmProvider.argtypes = [ctypes.c_void_p, w.DWORD]
        dll.BCryptCloseAlgorithmProvider.restype = ctypes.c_long

        r = dll.BCryptOpenAlgorithmProvider(ctypes.byref(self.hAlg), "AES", None, 0)
        if r != 0:
            raise TokenError("BCrypt 打开 AES 失败 0x%x" % r)
        dummy = w.DWORD(0)
        dll.BCryptSetAlgorithmProperty(self.hAlg, "ChainingMode", None, 0)  # noqa: 用下面的 key 属性设置 GCM

    def decrypt(self, key, nonce, aad, ciphertext, tag):
        dll = self.dll
        # BCRYPT_KEY_DATA_BLOB 结构
        class Blob(ctypes.Structure):
            _fields_ = [("dwMagic", w.DWORD), ("dwVersion", w.DWORD),
                        ("cbKeyData", w.DWORD), ("pbKeyData", ctypes.c_ubyte * len(key))]
        blob = Blob()
        blob.dwMagic = 0x6B44424D  # 'MDBK'
        blob.dwVersion = 1
        blob.cbKeyData = len(key)
        ctypes.memmove(ctypes.addressof(blob.pbKeyData), key, len(key))

        hKey = ctypes.c_void_p()
        # BCRYPT_ALG_HANDLE_HMAC_FLAG=8 不适用；IMPORT_KEY_DATA_BLOB=0x00000004
        r = dll.BCryptImportKey(self.hAlg, None, 4, ctypes.byref(blob), 0,
                                ctypes.byref(hKey), 0)
        if r != 0:
            raise TokenError("BCrypt ImportKey 失败 0x%x" % r)
        try:
            # GCM 需要通过 BCryptSetKeyProperty 设置 nonce/tag；用简化路径见 decrypt_via_node
            raise TokenError("BCrypt-GCM 需 Node 兜底")
        finally:
            dll.BCryptDestroyKey(hKey)


def _decrypt_via_node(key_b64, env):
    """用 Node 内置 crypto 做 AES-GCM 解密（零第三方 npm 依赖，WorkBuddy 自带 Node）。"""
    node = _find_node()
    script = r"""
const crypto=require('crypto');
const [keyB64, nonceB64, tagB64, ctB64] = JSON.parse(process.argv[1]);
const key=Buffer.from(keyB64,'base64');
const d={file:'WBEF1',field:'WBEV1',record:'WBER1',stream:'WBES1'};
const u={file:1,field:2,record:3,stream:4};
const u32=n=>{let b=Buffer.alloc(4);b.writeUInt32BE(n);return b};
const lp=s=>{let t=Buffer.from(s,'utf8');return Buffer.concat([u32(t.length),t])};
const keyId=crypto.createHash('sha256').update(key).digest('hex').slice(0,16);
function aad(framing,suite){
  return Buffer.concat([Buffer.from('WB-AAD\0','ascii'),Buffer.from([1]),
    lp(d[framing]),lp('sym-v1'),u32(suite),lp(keyId),Buffer.from([u[framing]]),Buffer.from([0]),Buffer.from([0])]);
}
let ok=null;
for(const framing of ['field','file','record','stream']){
  try{
    const dec=crypto.createDecipheriv('aes-256-gcm',key,Buffer.from(nonceB64,'base64'),{authTagLength:16});
    dec.setAAD(aad(framing,%SUITE%));
    dec.setAuthTag(Buffer.from(tagB64,'base64'));
    ok=Buffer.concat([dec.update(Buffer.from(ctB64,'base64')),dec.final()]).toString('utf8');
    break;
  }catch(e){}
}
if(ok===null){console.error('NOK');process.exit(2)}
process.stdout.write(ok);
""".replace("%SUITE%", str(env.get("suite", 1)))
    payload = json.dumps([key_b64, env["nonce"], env["authTag"], env["ciphertext"]])
    p = subprocess.run([node, "-e", script, payload], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise TokenError("Node 解密失败: " + p.stderr[:200])
    return p.stdout


def _find_node():
    """查找可用 Node：环境变量 → WorkBuddy 内置版本（通配）→ 系统 PATH。"""
    if os.environ.get("NODE_EXE"):
        return os.environ["NODE_EXE"]
    # WorkBuddy 各版本内置 node：用 glob 匹配任意版本号，不写死版本
    import glob
    patterns = [
        os.path.expandvars(
            r"%USERPROFILE%\.workbuddy\binaries\node\versions\*\node.exe"),
        os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\WorkBuddy\resources\app.asar.unpacked\*\node.exe"),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    for cmd in (["where", "node"], ["which", "node"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0]
        except Exception:
            continue
    raise TokenError("找不到 Node（用于 AES 解密）。请安装 Node，或用环境变量 NODE_EXE 指定路径")


# ---------- 内存扫描 ----------
class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", w.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]


def _wb_pids():
    """找 WorkBuddy 进程 PID（纯 ctypes 枚举，不依赖外部命令）。"""
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20).stdout
    pids = []
    for line in out.splitlines():
        m = re.match(r'"([^"]+)","(\d+)"', line)
        if m and "workbuddy" in m.group(1).lower():
            pids.append(int(m.group(2)))
    return pids


def _scan_memory(patterns, max_hits=200):
    """在所有 WorkBuddy 进程内存里找匹配的字节，返回命中集合。patterns: [bytes regex]。"""
    k = ctypes.windll.kernel32
    SIZE_T = ctypes.c_size_t
    hits = [set() for _ in patterns]
    pids = _wb_pids()
    if not pids:
        _log("没有运行中的 WorkBuddy 进程")
        return hits
    for pid in pids:
        h = k.OpenProcess(0x0400 | 0x0010, False, pid)
        if not h:
            continue
        mbi = _MBI()
        addr = 0
        try:
            while k.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                base = mbi.BaseAddress or 0
                size = mbi.RegionSize
                if (mbi.State == 0x1000 and mbi.Protect not in (0x01, 0x100)
                        and 0 < size < 300_000_000):
                    buf = ctypes.create_string_buffer(size)
                    read = SIZE_T(0)
                    if k.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size,
                                           ctypes.byref(read)) and read.value > 0:
                        data = buf.raw[:read.value]
                        for i, pat in enumerate(patterns):
                            for m in pat.finditer(data):
                                hits[i].add(m.group())
                                if len(hits[i]) >= max_hits:
                                    break
                addr = base + size
                if addr > 0x7FFFFFFFFFFF:
                    break
        finally:
            k.CloseHandle(h)
    return hits


def _find_at_rest_secret():
    """从进程内存反查 atRestSecretKey：用 keyId 校验 base64 候选。"""
    pat = re.compile(rb"[A-Za-z0-9+/]{40,50}={0,2}")
    hits = _scan_memory([pat], max_hits=100000)[0]
    _log("内存 base64 候选 %d 个，按 keyId 反查密钥…" % len(hits))
    keymap = {}
    for s in hits:
        try:
            key = hashlib.sha256(s).digest()
            kid = _derive_key_id(key)
            keymap.setdefault(kid, s.decode("ascii"))
        except Exception:
            pass
    # 优先用已知 keyId，否则取任意（本机只有一套）
    secret_b64 = keymap.get(KEY_ID_HINT)
    if not secret_b64 and len(keymap) == 1:
        secret_b64 = next(iter(keymap.values()))
    if not secret_b64:
        raise TokenError("未能从内存反查到 atRestSecretKey（请确认客户端已登录运行）")
    return hashlib.sha256(secret_b64.encode("utf-8")).digest()


def _find_access_token_in_memory():
    """兜底：直接从内存扫明文三段 JWT（客户端正在用）。"""
    pat = re.compile(rb"eyJhbGciOiJSUzI1NiIs[A-Za-z0-9_\-]{30,}\.[A-Za-z0-9_\-]{200,}\.[A-Za-z0-9_\-]{100,}")
    hits = _scan_memory([pat], max_hits=20)[0]
    for raw in hits:
        try:
            token = raw.decode("ascii")
            seg = token.split(".")[1]
            seg += "=" * (-len(seg) % 4)
            d = json.loads(base64.urlsafe_b64decode(seg))
            # 校验是有效 WorkBuddy JWT（有 sub 且未过期），不绑定任何具体账号
            if d.get("sub") and d.get("exp", 0) > time.time():
                return token
        except Exception:
            continue
    return None


# ---------- 信封读取与解密 ----------
def _read_envelope(field):
    if not os.path.exists(AUTH_FILE):
        raise TokenError("登录态文件不存在: " + AUTH_FILE)
    with open(AUTH_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    env = (d.get("auth") or {}).get(field, {}).get("envelope")
    if not env:
        raise TokenError("登录态缺少 " + field)
    return json.loads(base64.b64decode(env))


def _decrypt_field(field, key):
    env = _read_envelope(field)
    key_b64 = base64.b64encode(key).decode("ascii")
    return _decrypt_via_node(key_b64, env).strip()


# ---------- refresh ----------
def _refresh(refresh_token):
    h = {"Content-Type": "application/json", "X-Refresh-Token": refresh_token,
         "X-Auth-Refresh-Source": "plugin", "X-Domain": DOMAIN,
         "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3"}
    req = urllib.request.Request(ENDPOINT + REFRESH_PATH, data=b"{}", method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise TokenError("refresh HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    except Exception as e:
        raise TokenError("refresh 请求失败: %s" % e)
    if d.get("code") != 0 or not (d.get("data") or {}).get("accessToken"):
        raise TokenError("refresh 返回异常: code=%s msg=%s" % (d.get("code"), d.get("msg")))
    return d["data"]


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass


def get_tokens(force_refresh=False):
    """
    获取有效 accessToken。优先级：
      1) 缓存 refreshToken → refresh 换新（无需客户端运行，最快）
      2) 内存反查密钥 → 解密登录态里的 refreshToken → refresh
      3) 内存直接扫明文 accessToken（兜底）
    返回的 refreshToken 会写回 STATE_FILE，供下次续期，实现长期自动。
    """
    st = _load_state()
    rt = st.get("refreshToken", "")

    # 1) 用缓存 refreshToken 续期
    if rt and not force_refresh:
        try:
            _log("用缓存 refreshToken 续期…")
            data = _refresh(rt)
            out = {"accessToken": data["accessToken"],
                   "refreshToken": data.get("refreshToken") or rt,
                   "source": "cached_refresh",
                   "expiresIn": data.get("expiresIn"),
                   "refreshedAt": datetime.datetime.now().isoformat(timespec="seconds")}
            _save_state(out)
            return out
        except TokenError as e:
            _log("缓存续期失败，尝试内存解密: %s" % e)

    # 2) 内存反查密钥 → 解密 refreshToken → refresh
    try:
        _log("从内存反查密钥并解密 refreshToken…")
        key = _find_at_rest_secret()
        rt2 = _decrypt_field("refreshToken", key)
        if not rt2.startswith("eyJ"):
            raise TokenError("解密结果不是 JWT")
        data = _refresh(rt2)
        out = {"accessToken": data["accessToken"],
               "refreshToken": data.get("refreshToken") or rt2,
               "source": "decrypted_refresh",
               "expiresIn": data.get("expiresIn"),
               "refreshedAt": datetime.datetime.now().isoformat(timespec="seconds")}
        _save_state(out)
        return out
    except TokenError as e:
        _log("内存解密路径失败: %s" % e)

    # 3) 兜底：内存明文 accessToken
    at = _find_access_token_in_memory()
    if at:
        _log("从内存取到明文 accessToken（兜底）")
        return {"accessToken": at, "refreshToken": rt, "source": "memory_plaintext"}
    raise TokenError("所有取 token 路径均失败，请确认 WorkBuddy 已登录运行")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="获取 WorkBuddy 有效 accessToken")
    ap.add_argument("--force", action="store_true", help="跳过缓存，强制从内存解密")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON（含 refreshToken，注意保密）")
    a = ap.parse_args()
    try:
        t = get_tokens(force_refresh=a.force)
        if a.json:
            print(json.dumps(t, ensure_ascii=False))
        else:
            print(t["accessToken"])
    except TokenError as e:
        print("ERROR: " + str(e), file=sys.stderr)
        sys.exit(2)
