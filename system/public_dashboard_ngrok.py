import argparse
import http.client
import os
import subprocess
import sys
import time


def wait_dashboard_ready(host: str, port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/api/summary")
            resp = conn.getresponse()
            if resp.status == 200:
                return True
        except Exception:
            time.sleep(0.3)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return False


def terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    proc.terminate()
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dashboard and expose it via ngrok")
    parser.add_argument("--port", type=int, default=8080, help="Local dashboard port")
    parser.add_argument("--dashboard-host", default="127.0.0.1", help="Dashboard bind host")
    parser.add_argument("--log-file", default="material_log.csv", help="CSV log file path")
    parser.add_argument(
        "--authtoken",
        default="",
        help="ngrok authtoken (or set NGROK_AUTHTOKEN env var)",
    )
    parser.add_argument(
        "--basic-auth",
        default="",
        help="Optional HTTP basic auth in user:password format",
    )
    args = parser.parse_args()

    try:
        from pyngrok import ngrok
        from pyngrok.exception import PyngrokNgrokError
    except Exception as exc:
        print("pyngrok is not available in this environment.")
        print("Install with: python -m pip install pyngrok")
        print(f"Detail: {exc}")
        return 1

    script_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_script = os.path.join(script_dir, "web_dashboard.py")

    if not os.path.isfile(dashboard_script):
        print(f"Missing file: {dashboard_script}")
        return 1

    token = (args.authtoken or os.environ.get("NGROK_AUTHTOKEN", "")).strip()
    basic_auth = args.basic_auth.strip()

    dashboard_cmd = [
        sys.executable,
        dashboard_script,
        "--host",
        args.dashboard_host,
        "--port",
        str(args.port),
        "--log-file",
        args.log_file,
    ]

    dashboard_proc = subprocess.Popen(dashboard_cmd, cwd=script_dir)

    if not wait_dashboard_ready(args.dashboard_host, args.port):
        print("Dashboard did not become ready in time.")
        terminate_process(dashboard_proc)
        return 1

    tunnel = None
    try:
        if token:
            ngrok.set_auth_token(token)

        connect_args = {"addr": args.port, "bind_tls": True}
        if basic_auth:
            connect_args["basic_auth"] = basic_auth

        tunnel = ngrok.connect(**connect_args)
        print(f"Local dashboard: http://{args.dashboard_host}:{args.port}")
        print(f"Public URL: {tunnel.public_url}")
        if basic_auth:
            print("Basic auth is enabled for this tunnel.")
        print("Press Ctrl+C to stop both dashboard and tunnel.")

        while True:
            if dashboard_proc.poll() is not None:
                print("Dashboard process exited.")
                break
            time.sleep(0.8)

    except KeyboardInterrupt:
        print("Stopped by user.")
    except PyngrokNgrokError as exc:
        print("Failed to start ngrok tunnel.")
        print(str(exc))
        print("Tip: set NGROK_AUTHTOKEN or pass --authtoken <token>.")
        return 1
    finally:
        if tunnel is not None:
            try:
                ngrok.disconnect(tunnel.public_url)
            except Exception:
                pass

        try:
            ngrok.kill()
        except Exception:
            pass

        terminate_process(dashboard_proc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
