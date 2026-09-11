#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
import time
import urllib.parse
import base64
from typing import List, Dict, Optional

import requests
import urllib3

# 解决 Windows 控制台 UTF-8 输出编码问题
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 禁用 SSL 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 最新后端配置 ====================
# 支持主备地址自动容灾切换
AUTH_SERVERS = [
    "https://154.17.1.102/realms/vpn_application/protocol/openid-connect/token",
    "https://kc.huozhong.us/realms/vpn_application/protocol/openid-connect/token"
]
API_SERVERS = [
    "https://154.17.0.133/api/nodesystem/user",
    "https://api.huozhong.us/api/nodesystem/user"
]

# ⚠️ 这里填入你用“火种注册.py”注册成功的账号和密码
USERNAME = "qur0rhsf75"
PASSWORD = "v9x5hee99i"
CLIENT_ID = "vpn-user"
CLIENT_SECRET = "i16bYq4sXxlGl3s"

# ==================== 路径自适应优化 ====================
# 自动适配 Android (Termux) 与普通环境 (Windows/Linux/GitHub Actions)
if os.path.exists("/storage/emulated/0/Download"):
    OUTPUT_DIR = "/storage/emulated/0/Download"
else:
    # 默认输出到当前代码运行的目录，完美兼容 GitHub Actions
    OUTPUT_DIR = os.getcwd()

OUTPUT_FILE = os.path.join(OUTPUT_DIR, "huozhong_links.txt")
BASE64_FILE = os.path.join(OUTPUT_DIR, "huozhong_sub_base64.txt")

# ==================== 会话与基础 Headers ====================
session = requests.Session()
session.verify = False

BASE_HEADERS = {
    "User-Agent": "ktor-client",
    "X-App-Version": "1.1.21",
    "X-Device-OS": "Android",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

def retry_request(max_retries: int = 3, backoff_factor: float = 1.5):
    """重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        raise
                    wait = backoff_factor ** (attempt + 1)
                    print(f"  [重试 {attempt+1}/{max_retries}] {e}，{wait:.1f}s 后重试...")
                    time.sleep(wait)
            return None
        return wrapper
    return decorator

# ==================== 登录获取 Token ====================
def login_and_get_token() -> Optional[str]:
    print("[1/3] 正在登录获取最新 JWT Token...")
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
    }
    headers = {
        **BASE_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Host": "kc.huozhong.us"
    }

    for auth_url in AUTH_SERVERS:
        try:
            resp = session.post(auth_url, data=payload, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token")
                if token:
                    expires = data.get("expires_in", 0) // 60
                    print(f"  [OK] 登录成功！Token 有效期约 {expires} 分钟")
                    return token
            else:
                print(f"  [!] 服务器 {auth_url} 返回状态码 {resp.status_code}")
        except Exception as e:
            print(f"  [!] 连接 {auth_url} 异常: {e}")

    print("  [ERROR] 登录失败，请检查账号密码或后端连通性")
    return None

# ==================== 获取节点列表 ====================
@retry_request(max_retries=3)
def get_node_list(token: str) -> List[Dict]:
    print("[2/3] 正在拉取全量节点列表...")
    headers = {
        **BASE_HEADERS,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Host": "api.huozhong.us"
    }
    
    for api_url in API_SERVERS:
        try:
            url = f"{api_url}/nodeList?platform=android"
            resp = session.post(url, headers=headers, json={}, timeout=15)
            if resp.status_code == 200:
                nodes = resp.json()
                if isinstance(nodes, list):
                    print(f"  [OK] 成功获取 {len(nodes)} 个可用节点")
                    return nodes
        except Exception:
            continue
    raise Exception("所有 API 节点服务器均无法连接")

# ==================== 获取单个节点实时配置 ====================
@retry_request(max_retries=3)
def get_client_config(node_id: int, token: str) -> Optional[Dict]:
    headers = {
        **BASE_HEADERS,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Host": "api.huozhong.us"
    }
    for api_url in API_SERVERS:
        try:
            url = f"{api_url}/clientConfig"
            payload = {"nodeId": node_id, "ipv6": False}
            resp = session.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            continue
    return None

# ==================== 节点名称提取 ====================
def extract_node_name(node: Dict) -> str:
    name_parts = []
    if region := node.get("regionNameCn"):
        name_parts.append(region.strip())
    if name := node.get("nameCn"):
        name_parts.append(name.strip())
    elif name := node.get("nameEn"):
        name_parts.append(name.strip())
    
    if tag := node.get("tagCn"):
        name_parts.append(f"({tag.strip()})")

    result = " - ".join(name_parts) if name_parts else f"Node-{node.get('nodeId', '未知')}"
    return result

# ==================== 链接生成器 ====================
def generate_trojan_link(config: Dict, node_name: str) -> str:
    servers = config.get("settings", {}).get("servers", [])
    if not servers:
        raise ValueError("缺少 servers 配置")
    
    s = servers[0]
    address = s.get("address")
    port = s.get("port")
    password = s.get("password")
    if not all([address, port, password]):
        raise ValueError("Trojan 缺少核心连接信息")

    stream = config.get("streamSettings", {})
    tls = stream.get("tlsSettings", {})
    ws = stream.get("wsSettings", {})
    grpc = stream.get("grpcSettings", {})
    network = stream.get("network", "tcp")

    params = {}
    
    if stream.get("security") == "tls":
        params["security"] = "tls"
        if sni := tls.get("serverName"):
            params["sni"] = sni
        if tls.get("allowInsecure") is not None:
            params["allowInsecure"] = "1" if tls.get("allowInsecure") else "0"
        if fp := tls.get("fingerprint"):
            params["fp"] = fp
        params["alpn"] = "http/1.1"

    params["type"] = network
    if network == "ws":
        if path := ws.get("path"):
            params["path"] = path
        params["host"] = tls.get("serverName", "vpn-node.internal")
    elif network == "grpc" and (svc := grpc.get("serviceName")):
        params["serviceName"] = svc

    query = urllib.parse.urlencode(params)
    remark = urllib.parse.quote(node_name)
    return f"trojan://{password}@{address}:{port}?{query}#{remark}"

def generate_vless_link(config: Dict, node_name: str) -> str:
    vnext = config.get("settings", {}).get("vnext", [])[0]
    user = vnext.get("users", [])[0]
    stream = config.get("streamSettings", {})
    network = stream.get("network", "tcp")

    params = {
        "encryption": user.get("encryption", "none"),
        "type": network,
    }

    if stream.get("security") == "reality":
        reality = stream.get("realitySettings", {})
        params.update({
            "security": "reality",
            "pbk": reality.get("publicKey", ""),
            "fp": reality.get("fingerprint", "chrome"),
            "sni": reality.get("serverName", ""),
            "sid": reality.get("shortId", ""),
            "headerType": "none",
        })
    elif stream.get("security") == "tls":
        tls = stream.get("tlsSettings", {})
        params["security"] = "tls"
        if sni := tls.get("serverName"):
            params["sni"] = sni
        if tls.get("allowInsecure") is not None:
            params["allowInsecure"] = "1" if tls.get("allowInsecure") else "0"
        if fp := tls.get("fingerprint"):
            params["fp"] = fp
        params["alpn"] = "http/1.1"

    if network == "ws":
        ws = stream.get("wsSettings", {})
        if path := ws.get("path"):
            params["path"] = path
        params["host"] = params.get("sni", "vpn-node.internal")

    query = urllib.parse.urlencode(params)
    remark = urllib.parse.quote(node_name)
    return f"vless://{user['id']}@{vnext['address']}:{vnext['port']}?{query}#{remark}"

# ==================== 主入口 ====================
def main():
    print("=" * 60)
    print("      火种VPN - 节点全量订阅提取器 (2026 最新版)")
    print("=" * 60)
    print(f"文本节点文件: {OUTPUT_FILE}")
    print(f"Base64订阅文件: {BASE64_FILE}\n")

    token = login_and_get_token()
    if not token:
        sys.exit(1)

    try:
        nodes = get_node_list(token)
    except Exception as e:
        print(f"获取节点列表失败: {e}")
        sys.exit(1)

    if not nodes:
        print("节点列表为空")
        sys.exit(1)

    # 准备写入文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 火种VPN 节点订阅 - 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    print(f"\n[3/3] 正在逐个解析 {len(nodes)} 个节点的实时配置并生成链接...")
    success = 0
    
    for idx, node in enumerate(nodes, 1):
        node_id = node.get("nodeId")
        if not node_id:
            continue
        
        node_name = extract_node_name(node)
        
        try:
            config = get_client_config(node_id, token)
        except Exception as e:
            print(f"  [{idx:3d}/{len(nodes)}] [ERROR] 节点 {node_id} 获取配置失败: {e}")
            continue

        if not config:
            continue

        protocol = config.get("protocol", "").lower()
        link = None
        try:
            if protocol == "trojan":
                link = generate_trojan_link(config, node_name)
            elif protocol == "vless":
                link = generate_vless_link(config, node_name)
            else:
                print(f"  [{idx:3d}/{len(nodes)}] [SKIP] 未知协议 {protocol}")
                continue
        except Exception as e:
            print(f"  [{idx:3d}/{len(nodes)}] [ERROR] 生成链接异常: {e}")
            continue

        if link:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(link + "\n")
            success += 1
            print(f"  [{idx:3d}/{len(nodes)}] [OK] [{protocol.upper()}] {node_name}")

    # ==================== 生成 Base64 订阅 ====================
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip() and not line.startswith("#")]
        
        with open(BASE64_FILE, "w", encoding="utf-8") as f:
            f.write(base64.b64encode(("\n".join(lines)).encode('utf-8')).decode('utf-8'))
        print(f"\n[+] Base64 订阅已成功生成，支持导入代理客户端使用！")
    except Exception as e:
        print(f"\n[-] Base64 生成失败: {e}")
    # ========================================================

    print("\n" + "=" * 60)
    print(f"处理完成！共成功导出 {success} 条有效节点链接")
    print(f"文件位置: \n1. {OUTPUT_FILE}\n2. {BASE64_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
