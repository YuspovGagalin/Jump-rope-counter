#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ジャンプ＆縄跳びカウント判定アプリ用 ローカルサーバー

Google Chrome は file:// で開いたページにカメラを許可しないため、
このスクリプトでフォルダを配信してから http://localhost:8000/ を開いてください。

使い方:
    PCのChromeで使う場合        python3 serve.py
    スマホのChromeで使う場合    python3 serve.py --https
    ポートを変える場合          python3 serve.py --port 9000

    ※ Windows では python3 の代わりに py を使ってください。
"""

import argparse
import http.server
import os
import socket
import ssl
import subprocess
import sys
import webbrowser

CERT_FILE = "localhost_cert.pem"
KEY_FILE = "localhost_key.pem"


class Handler(http.server.SimpleHTTPRequestHandler):
    """キャッシュを無効にして、HTMLを編集したらすぐ反映されるようにする"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        # アクセスログは簡潔に
        sys.stderr.write("  %s\n" % (fmt % args))


def get_lan_ip():
    """このPCがLAN内で持っているIPアドレスを調べる（外部へは接続しない）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None
    finally:
        s.close()


def make_self_signed_cert(lan_ip):
    """自己署名証明書を作る。cryptography があればそれを使い、無ければ openssl を呼ぶ。"""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        print("既存の証明書を使用します: %s / %s" % (CERT_FILE, KEY_FILE))
        return True

    # 方法1: cryptography モジュール
    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        print("証明書を作成しています (cryptography)...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"localhost")])

        alt_names = [x509.DNSName(u"localhost")]
        try:
            import ipaddress
            alt_names.append(x509.IPAddress(ipaddress.ip_address(u"127.0.0.1")))
            if lan_ip:
                alt_names.append(x509.IPAddress(ipaddress.ip_address(unicode_str(lan_ip))))
        except Exception:
            pass

        try:
            now = datetime.datetime.now(datetime.timezone.utc)
        except AttributeError:
            now = datetime.datetime.utcnow()
        cert = (x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=825))
                .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
                .sign(key, hashes.SHA256()))

        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()))
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except ImportError:
        pass
    except Exception as e:
        print("cryptography での作成に失敗しました: %s" % e)

    # 方法2: openssl コマンド
    print("証明書を作成しています (openssl)...")
    san = "DNS:localhost,IP:127.0.0.1"
    if lan_ip:
        san += ",IP:%s" % lan_ip
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", KEY_FILE, "-out", CERT_FILE,
        "-days", "825", "-subj", "/CN=localhost",
        "-addext", "subjectAltName=%s" % san,
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        pass

    # -addext が使えない古い openssl 向けに、拡張なしでもう一度
    try:
        subprocess.check_call(cmd[:-2], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print("\n[エラー] 証明書を作成できませんでした。")
        print("  次のいずれかをお試しください。")
        print("   1) pip install cryptography を実行してから、もう一度 --https で起動する")
        print("   2) openssl コマンドを使えるようにする")
        print("   3) --https を付けずに起動し、PCのChromeから http://localhost:%d/ で使う" % 8000)
        print("  詳細: %s" % e)
        return False


def unicode_str(v):
    return v if isinstance(v, str) else v.decode("utf-8")


def find_app_file():
    """同じフォルダにあるアプリ本体のHTMLを探す"""
    candidates = sorted(f for f in os.listdir(".")
                        if f.startswith("jump_rope_counter") and f.endswith(".html")
                        and "_spec" not in f)
    return candidates[-1] if candidates else None


def main():
    parser = argparse.ArgumentParser(description="縄跳びカウンター用ローカルサーバー")
    parser.add_argument("--https", action="store_true",
                        help="HTTPSで起動する（スマホから使う場合に必要）")
    parser.add_argument("--port", type=int, default=None, help="ポート番号")
    parser.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    args = parser.parse_args()

    port = args.port if args.port else (8443 if args.https else 8000)
    lan_ip = get_lan_ip()
    app = find_app_file()
    path = "/" + app if app else "/"

    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)

    scheme = "http"
    if args.https:
        if not make_self_signed_cert(lan_ip):
            sys.exit(1)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    print("")
    print("=" * 62)
    print("  縄跳びカウンター ローカルサーバーを起動しました")
    print("=" * 62)
    if app:
        print("  配信するファイル : %s" % app)
    else:
        print("  [注意] jump_rope_counter*.html がこのフォルダに見つかりません")
    print("")
    print("  このPCのChromeから:")
    print("      %s://localhost:%d%s" % (scheme, port, path))
    if lan_ip:
        print("")
        print("  同じWi-FiにつないだスマホのChromeから:")
        print("      %s://%s:%d%s" % (scheme, lan_ip, port, path))
        if not args.https:
            print("      ※ http:// ではスマホのカメラを使えません。")
            print("         スマホで使う場合は --https を付けて起動し直してください。")
        else:
            print("      ※ 証明書の警告画面が出たら")
            print("         「詳細設定」→「(安全ではありません) にアクセスする」を選んでください。")
    print("")
    print("  終了するには Ctrl+C を押してください。")
    print("=" * 62)
    print("")

    if not args.no_open:
        try:
            webbrowser.open("%s://localhost:%d%s" % (scheme, port, path))
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを停止しました。")
        httpd.server_close()


if __name__ == "__main__":
    main()
