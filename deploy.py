#!/usr/bin/env python3
"""Build and deploy StockWeb, then retire the legacy StockInfoWeb service.

Configuration is read from deploy_config.json (which is gitignored).  On the
first run it can inherit the SSH fields from the legacy project's config:

    python deploy.py --from-config E:\\code\\Trade\\StockInfoWeb\\deploy_config.json
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    # Package-manager output can contain box-drawing characters that the
    # default Windows console code page cannot encode.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - used only by deploy operators
    raise SystemExit("请先安装部署依赖：python -m pip install paramiko") from exc


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "deploy_config.json"
ARCHIVE_NAME = "stockweb-deploy.tar.gz"

DEFAULTS: dict[str, Any] = {
    "host": "",
    "port": 22,
    "username": "root",
    "password": "",
    "key_filename": "",
    "remote_dir": "/var/www/stockweb",
    "domain_or_ip": "",
    "backend_port": 8001,
    "environment": {},
}
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", ".next", "__pycache__", ".idea", ".vscode"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 的根节点必须是 JSON 对象。")
    return value


def load_config(source_config: str | None) -> dict[str, Any]:
    config = dict(DEFAULTS)
    if source_config:
        source_path = Path(source_config)
        legacy = load_json(source_path)
        # A legacy config describes the old application's directory and port.
        # Import only connection fields, never its application topology.
        for key in ("host", "port", "username", "password", "key_filename", "domain_or_ip"):
            if legacy.get(key):
                config[key] = legacy[key]
        # The retired project stored its TuData token in source code. Move it
        # only into the new server's mode-600 environment file; it is never
        # copied into this repository or printed by the deployer.
        token_source = source_path.parent / "backend" / "data_capture" / "realtime_quote.py"
        if token_source.exists():
            matched = re.search(r"set_token\(\s*['\"]([^'\"]+)['\"]\s*\)", token_source.read_text(encoding="utf-8"))
            if matched:
                config["environment"] = {"TUDATA_TOKEN": matched.group(1)}
    if CONFIG_PATH.exists():
        config.update(load_json(CONFIG_PATH))
    if not config["host"]:
        raise ValueError("缺少服务器地址。请复制 deploy_config.template.json 为 deploy_config.json，或传入 --from-config。")
    if not config["domain_or_ip"]:
        config["domain_or_ip"] = config["host"]
    if not str(config["remote_dir"]).startswith("/"):
        raise ValueError("remote_dir 必须是 Linux 绝对路径。")
    if not config.get("password") and not config.get("key_filename"):
        raise ValueError("请在 deploy_config.json 中提供 password 或 key_filename。")
    return config


def run_local(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("[本机]", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def build_frontend() -> None:
    frontend = ROOT / "frontend"
    environment = os.environ.copy()
    environment["NEXT_PUBLIC_API_BASE_URL"] = "/api"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    run_local([npm, "ci", "--no-audit", "--no-fund"], frontend, environment)
    run_local([npm, "run", "build"], frontend, environment)
    if not (frontend / "out" / "index.html").exists():
        raise RuntimeError("前端静态构建未生成 frontend/out/index.html。")


def archive_project() -> Path:
    archive = ROOT / ARCHIVE_NAME
    if archive.exists():
        archive.unlink()

    def include(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        if any(part in EXCLUDED_PARTS or part.endswith((".pyc", ".pyo")) for part in parts):
            return None
        if info.name.endswith((".env", ".env.local")):
            return None
        return info

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(ROOT / "backend", arcname="backend", filter=include)
        tar.add(ROOT / "frontend" / "out", arcname="frontend/out", filter=include)
    return archive


def connect(config: dict[str, Any]) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    arguments: dict[str, Any] = {
        "hostname": config["host"],
        "port": int(config["port"]),
        "username": config["username"],
        "timeout": 20,
    }
    if config.get("key_filename"):
        arguments["key_filename"] = config["key_filename"]
    else:
        arguments["password"] = config["password"]
    print(f"[SSH] 连接 {config['username']}@{config['host']}:{config['port']}")
    client.connect(**arguments)
    return client


def execute(client: paramiko.SSHClient, command: str, description: str) -> None:
    print(f"[服务器] {description}")
    _, stdout, stderr = client.exec_command(command, get_pty=True)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if output.strip():
        print(output.rstrip())
    if status:
        raise RuntimeError(f"{description}失败（退出码 {status}）：{error.strip() or output.strip()}")


def upload(client: paramiko.SSHClient, archive: Path, remote_dir: str, user: str) -> str:
    remote_archive = posixpath.join(remote_dir, ARCHIVE_NAME)
    execute(client, f"sudo mkdir -p {shlex.quote(remote_dir)} && sudo chown {shlex.quote(user)}:{shlex.quote(user)} {shlex.quote(remote_dir)}", "创建部署目录")
    print("[上传]", archive.name)
    sftp = client.open_sftp()
    try:
        sftp.put(str(archive), remote_archive)
    finally:
        sftp.close()
    return remote_archive


def encoded_file(contents: str) -> str:
    return base64.b64encode(contents.encode()).decode()


def deploy(client: paramiko.SSHClient, config: dict[str, Any], remote_archive: str) -> None:
    remote_dir = str(config["remote_dir"]).rstrip("/")
    user = str(config["username"])
    port = int(config["backend_port"])
    domain = str(config["domain_or_ip"])
    qdir, quser = shlex.quote(remote_dir), shlex.quote(user)

    execute(
        client,
        "if command -v apt-get >/dev/null 2>&1; then "
        "sudo apt-get update -y && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx curl; "
        "elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y python3 python3-pip nginx curl; "
        "elif command -v yum >/dev/null 2>&1; then sudo yum install -y python3 python3-pip nginx curl; "
        "else echo '不支持的 Linux 包管理器'; exit 1; fi",
        "安装运行依赖",
    )
    execute(
        client,
        f"sudo rm -rf {qdir}/release.new && sudo mkdir -p {qdir}/release.new && "
        f"sudo tar -xzf {shlex.quote(remote_archive)} -C {qdir}/release.new && "
        f"sudo rm -f {shlex.quote(remote_archive)} && sudo chown -R {quser}:{quser} {qdir}/release.new",
        "解压新版本",
    )
    environment = {str(key): str(value) for key, value in dict(config.get("environment") or {}).items() if value}
    environment.setdefault("CORS_ORIGINS", f"http://{domain},https://{domain}")
    env_text = "\n".join(f"{key}={value}" for key, value in environment.items()) + "\n"
    execute(
        client,
        f"echo {shlex.quote(encoded_file(env_text))} | base64 -d | sudo tee {qdir}/release.new/backend/.env >/dev/null && "
        f"sudo chown {quser}:{quser} {qdir}/release.new/backend/.env && sudo chmod 600 {qdir}/release.new/backend/.env",
        "写入运行环境变量",
    )

    service = f"""[Unit]
Description=StockWeb FastAPI Backend
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={remote_dir}/current/backend
EnvironmentFile={remote_dir}/current/backend/.env
ExecStart={remote_dir}/current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port {port} --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    execute(
        client,
        f"echo {shlex.quote(encoded_file(service))} | base64 -d | sudo tee /etc/systemd/system/stockweb-backend.service >/dev/null && "
        f"sudo rm -rf {qdir}/previous && if [ -e {qdir}/current ]; then sudo mv {qdir}/current {qdir}/previous; fi && "
        f"sudo mv {qdir}/release.new {qdir}/current && sudo chown -R {quser}:{quser} {qdir}/current && "
        f"cd {qdir}/current/backend && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt && "
        "sudo systemctl daemon-reload && sudo systemctl enable stockweb-backend && sudo systemctl restart stockweb-backend",
        "切换、安装并启动新后端",
    )
    execute(client, f"curl --fail --silent --show-error http://127.0.0.1:{port}/health", "验证新后端健康状态")
    execute(client, f"test \"$(curl --fail --silent --show-error 'http://127.0.0.1:{port}/api/realtime-price/raw?code=600519')\" != 0", "验证实时股价兼容接口")

    nginx = f"""server {{
    listen 80;
    server_name {domain};

    location /api/ {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 15s;
        proxy_read_timeout 60s;
    }}

    location / {{
        root {remote_dir}/current/frontend/out;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}
"""
    execute(
        client,
        f"echo {shlex.quote(encoded_file(nginx))} | base64 -d | sudo tee /tmp/stockweb.nginx >/dev/null && "
        "if [ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ]; then "
        "sudo cp /tmp/stockweb.nginx /etc/nginx/sites-available/stockweb; sudo ln -sfn /etc/nginx/sites-available/stockweb /etc/nginx/sites-enabled/stockweb; "
        "sudo rm -f /etc/nginx/sites-enabled/stock-info-web /etc/nginx/sites-enabled/default; "
        "else sudo rm -f /etc/nginx/conf.d/stock-info-web.conf; sudo cp /tmp/stockweb.nginx /etc/nginx/conf.d/stockweb.conf; fi && "
        "sudo nginx -t && sudo systemctl enable nginx && sudo systemctl reload nginx",
        "切换 Nginx 到 StockWeb",
    )
    execute(client, "sudo systemctl disable --now stock-backend 2>/dev/null || true", "停止旧 StockInfoWeb 后端")
    time.sleep(2)
    execute(client, f"curl --fail --silent --show-error http://127.0.0.1:{port}/health", "最终健康检查")


def finalize(client: paramiko.SSHClient, config: dict[str, Any]) -> None:
    """Complete a safe cutover after a prior deploy reached backend health."""
    remote_dir = str(config["remote_dir"]).rstrip("/")
    port = int(config["backend_port"])
    domain = str(config["domain_or_ip"])
    execute(client, f"curl --fail --silent --show-error http://127.0.0.1:{port}/health", "验证新后端健康状态")
    execute(client, f"test \"$(curl --fail --silent --show-error 'http://127.0.0.1:{port}/api/realtime-price/raw?code=600519')\" != 0", "验证实时股价兼容接口")
    nginx = f"""server {{
    listen 80;
    server_name {domain};

    location /api/ {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 15s;
        proxy_read_timeout 60s;
    }}

    location / {{
        root {remote_dir}/current/frontend/out;
        index index.html;
        try_files $uri $uri/ /index.html;
    }}
}}
"""
    execute(
        client,
        f"echo {shlex.quote(encoded_file(nginx))} | base64 -d | sudo tee /tmp/stockweb.nginx >/dev/null && "
        "if [ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ]; then "
        "sudo cp /tmp/stockweb.nginx /etc/nginx/sites-available/stockweb; sudo ln -sfn /etc/nginx/sites-available/stockweb /etc/nginx/sites-enabled/stockweb; "
        "sudo rm -f /etc/nginx/sites-enabled/stock-info-web /etc/nginx/sites-enabled/default; "
        "else sudo rm -f /etc/nginx/conf.d/stock-info-web.conf; sudo cp /tmp/stockweb.nginx /etc/nginx/conf.d/stockweb.conf; fi && "
        "sudo nginx -t && sudo systemctl enable nginx && sudo systemctl reload nginx",
        "切换 Nginx 到 StockWeb",
    )
    execute(client, "sudo systemctl disable --now stock-backend 2>/dev/null || true", "停止旧 StockInfoWeb 后端")
    execute(client, "curl --fail --silent --show-error http://127.0.0.1/ >/dev/null", "验证新站点首页")
    execute(client, "test \"$(curl --fail --silent --show-error 'http://127.0.0.1/api/realtime-price/raw?code=600519')\" != 0", "验证 Nginx 实时股价接口")


def repair_static_site(client: paramiko.SSHClient, config: dict[str, Any]) -> None:
    remote_dir = str(config["remote_dir"]).rstrip("/")
    archive = archive_project()
    try:
        remote_archive = upload(client, archive, remote_dir, str(config["username"]))
        qdir = shlex.quote(remote_dir)
        execute(
            client,
            f"sudo mkdir -p {qdir}/current/frontend && sudo tar -xzf {shlex.quote(remote_archive)} -C {qdir}/current frontend/out && "
            f"sudo rm -f {shlex.quote(remote_archive)} && sudo chown -R {shlex.quote(str(config['username']))}:{shlex.quote(str(config['username']))} {qdir}/current/frontend/out && "
            "sudo nginx -t && sudo systemctl reload nginx",
            "补传静态前端并重载 Nginx",
        )
        execute(client, "curl --fail --silent --show-error http://127.0.0.1/ >/dev/null", "验证新站点首页")
        execute(client, "test \"$(curl --fail --silent --show-error 'http://127.0.0.1/api/realtime-price/raw?code=600519')\" != 0", "验证 Nginx 实时股价接口")
    finally:
        if archive.exists():
            archive.unlink()


def set_tudata_token(client: paramiko.SSHClient, config: dict[str, Any], token: str) -> None:
    remote_dir = str(config["remote_dir"]).rstrip("/")
    env_path = f"{remote_dir}/current/backend/.env"
    q_env_path = shlex.quote(env_path)
    execute(
        client,
        f"sudo sed -i '/^TUDATA_TOKEN=/d' {q_env_path} && "
        f"echo {shlex.quote(encoded_file(f'TUDATA_TOKEN={token}\\n'))} | base64 -d | sudo tee -a {q_env_path} >/dev/null && "
        f"sudo chown {shlex.quote(str(config['username']))}:{shlex.quote(str(config['username']))} {q_env_path} && sudo chmod 600 {q_env_path} && "
        "sudo systemctl restart stockweb-backend",
        "更新 TuData Token 并重启后端",
    )
    execute(
        client,
        f"cd {shlex.quote(remote_dir)}/current/backend && .venv/bin/python -c \"from app.services.tudata_provider import provider; print(provider.latest_trade_date())\"",
        "验证 TuData trade_cal",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="部署 StockWeb 并停用旧 StockInfoWeb 服务")
    parser.add_argument("--from-config", help="读取旧项目的 deploy_config.json 作为 SSH 配置来源")
    parser.add_argument("--status", action="store_true", help="仅查看服务器服务状态，不做修改")
    parser.add_argument("--logs", action="store_true", help="查看新后端最近的 systemd 日志，不做修改")
    parser.add_argument("--nginx-logs", action="store_true", help="查看 Nginx 最近错误日志，不做修改")
    parser.add_argument("--finalize", action="store_true", help="在已验证的新后端上完成 Nginx 和旧服务切换")
    parser.add_argument("--repair-static", action="store_true", help="仅补传静态前端并验证 Nginx 站点")
    parser.add_argument("--set-tudata-token", help="更新服务器 TuData Token 并验证 trade_cal")
    parser.add_argument("--skip-build", action="store_true", help="复用现有 frontend/out 静态构建产物")
    arguments = parser.parse_args()
    if arguments.status:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            execute(
                client,
                "for service in stockweb-backend stock-backend nginx; do "
                "printf '%s=' \"$service\"; systemctl is-active \"$service\" 2>/dev/null || true; done; "
                "printf 'stockweb_health='; curl --silent --max-time 3 http://127.0.0.1:8001/health || true",
                "读取服务器服务状态",
            )
        finally:
            client.close()
        return
    if arguments.logs:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            execute(
                client,
                "sudo systemctl status stockweb-backend --no-pager -n 30 || true; "
                "sudo journalctl -u stockweb-backend --no-pager -n 80 || true",
                "读取新后端日志",
            )
        finally:
            client.close()
        return
    if arguments.nginx_logs:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            execute(
                client,
                "sudo tail -n 80 /var/log/nginx/error.log 2>/dev/null || true; "
                "sudo ls -ld /var/www /var/www/stockweb /var/www/stockweb/current /var/www/stockweb/current/frontend /var/www/stockweb/current/frontend/out; "
                "sudo ls -la /var/www/stockweb/current/frontend/out | head -n 30",
                "读取 Nginx 错误日志和静态文件状态",
            )
        finally:
            client.close()
        return
    if arguments.finalize:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            finalize(client, config)
        finally:
            client.close()
        print("切换完成：StockWeb 已接管站点，旧 stock-backend 已停止。")
        return
    if arguments.repair_static:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            repair_static_site(client, config)
        finally:
            client.close()
        print("静态前端已修复并验证。")
        return
    if arguments.set_tudata_token:
        config = load_config(arguments.from_config)
        client = connect(config)
        try:
            set_tudata_token(client, config, arguments.set_tudata_token)
        finally:
            client.close()
        print("TuData Token 已更新并验证。")
        return
    try:
        config = load_config(arguments.from_config)
        if arguments.skip_build:
            if not (ROOT / "frontend" / "out" / "index.html").exists():
                raise RuntimeError("未找到 frontend/out/index.html，不能跳过前端构建。")
        else:
            build_frontend()
        archive = archive_project()
        client = connect(config)
        try:
            remote_archive = upload(client, archive, str(config["remote_dir"]), str(config["username"]))
            deploy(client, config, remote_archive)
        finally:
            client.close()
    finally:
        if (ROOT / ARCHIVE_NAME).exists():
            (ROOT / ARCHIVE_NAME).unlink()
    print("部署完成：StockWeb 已接管站点，旧 stock-backend 已停止。")


if __name__ == "__main__":
    main()
