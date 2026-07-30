#!/usr/bin/env python3
"""检查 TLS 证书到期时间，临近到期时告警。

V1.0 item 2: certbot / Caddy 自动续期监控。
Caddy 自动续期（LE 90 天证书，~30 天前续），但续期可能静默失败
（端口变更、ACME 限流等）。本脚本定期检查线上证书实际剩余天数，
低于阈值时退出码非零，供 cron / 监控系统告警。

用法:
    python scripts/check_cert_expiry.py                          # 默认检查 seewo.researchkit.online:443
    python scripts/check_cert_expiry.py --host example.com --warn-days 14
    python scripts/check_cert_expiry.py --host seewo.researchkit.online --warn-days 30 --crit-days 7

退出码:
    0 = 正常（剩余天数 > warn）
    1 = 警告（剩余天数 <= warn）
    2 = 严重（剩余天数 <= crit 或连接失败）
"""
from __future__ import annotations

import argparse
import socket
import ssl
import sys
from datetime import datetime, timezone


def check_cert(host: str, port: int = 443) -> datetime:
    """连接 host:port 获取证书到期时间（UTC naive）。"""
    ctx = ssl.create_default_context()
    # 不验证主机名（我们只要证书日期，且可能通过 IP 访问）
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert = ssock.getpeercert()
    # notAfter 格式: 'Jul 30 12:00:00 2026 GMT'
    return datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="TLS 证书到期检查")
    parser.add_argument("--host", default="seewo.researchkit.online", help="目标域名")
    parser.add_argument("--port", type=int, default=443, help="端口")
    parser.add_argument("--warn-days", type=int, default=30, help="警告阈值（天）")
    parser.add_argument("--crit-days", type=int, default=7, help="严重阈值（天）")
    args = parser.parse_args()

    try:
        expires_at = check_cert(args.host, args.port)
    except Exception as exc:  # noqa: BLE001
        print(f"CRITICAL: 无法获取 {args.host}:{args.port} 证书: {exc}")
        return 2

    now = datetime.utcnow()
    remaining = (expires_at - now).days
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M UTC")

    if remaining <= args.crit_days:
        print(f"CRITICAL: {args.host} 证书 {remaining} 天后到期（{expires_str}），<= {args.crit_days} 天")
        return 2
    if remaining <= args.warn_days:
        print(f"WARN: {args.host} 证书 {remaining} 天后到期（{expires_str}），<= {args.warn_days} 天")
        return 1
    print(f"OK: {args.host} 证书 {remaining} 天后到期（{expires_str}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
