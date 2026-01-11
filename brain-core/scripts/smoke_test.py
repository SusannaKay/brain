#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _request_json(url: str, headers: dict) -> dict:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _wait_for_health(base_url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            data = _request_json(f"{base_url}/health", headers={})
            if isinstance(data, dict) and data.get("ok") is True:
                return
        except (urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.2)
    raise RuntimeError("Health check did not become ready in time.")


def _fail(message: str, repo_root: Path) -> None:
    if not (repo_root / "telegram_bot").exists():
        print(f"SMOKE DEBUG: repo_root={repo_root} missing telegram_bot")
    raise RuntimeError(message)


def _check_bot_config(repo_root: Path) -> None:
    os.environ["BRAIN_URL"] = "http://brain-api:8000"
    os.environ["BRAIN_SHARED_TOKEN"] = "smoke-token"
    os.environ["BRAIN_TELEGRAM_KEY"] = "smoke-telegram-key"
    os.environ["TELEGRAM_BOT_TOKEN"] = "smoke-telegram-bot-token"
    os.environ["TZ"] = "Europe/Rome"
    os.environ["DIGEST_TIME"] = "08:00"
    os.environ["MOOD_TIME"] = "21:30"
    os.environ["WEEKLY_DIGEST_TIME"] = "20:00"
    os.environ["WEEKLY_DIGEST_WEEKDAY"] = "sun"
    os.environ["DIGEST_CHAT_IDS"] = "1,2"
    os.environ["BRAIN_BOT_RATE_LIMIT_SECONDS"] = "1.0"
    os.environ["DIGEST_ENABLED"] = "false"
    os.environ["WEEKLY_DIGEST_ENABLED"] = "true"
    os.environ["BRAIN_BOT_DB_PATH"] = "/tmp/bot.db"

    sys.path.insert(0, str(repo_root))
    import importlib

    importlib.invalidate_caches()
    sys.modules.pop("telegram_bot", None)
    sys.modules.pop("telegram_bot.config", None)

    bot_config = importlib.import_module("telegram_bot.config")
    if bot_config.BRAIN_URL != "http://brain-api:8000":
        _fail("Unexpected BRAIN_URL in bot config.", repo_root)
    if not bot_config.BRAIN_TOKEN or not bot_config.BRAIN_TELEGRAM_KEY or not bot_config.TELEGRAM_BOT_TOKEN:
        _fail("Bot tokens not set in config.", repo_root)
    digest_tz = bot_config.get_digest_tz()
    if digest_tz.key != "Europe/Rome":
        _fail("Unexpected TZ in bot config.", repo_root)
    if bot_config.DIGEST_TIME is None or bot_config.MOOD_TIME is None or bot_config.WEEKLY_DIGEST_TIME is None:
        _fail("Digest/mood times not parsed.", repo_root)
    print(
        "BOT CONFIG OK: "
        f"BRAIN_URL={bot_config.BRAIN_URL} "
        f"token_set={bool(bot_config.BRAIN_TOKEN)} "
        f"telegram_token_set={bool(bot_config.TELEGRAM_BOT_TOKEN)} "
        f"tz={digest_tz.key} "
        f"digest_time={bot_config.DIGEST_TIME} "
        f"mood_time={bot_config.MOOD_TIME} "
        f"weekly_time={bot_config.WEEKLY_DIGEST_TIME}"
    )


def main() -> int:
    port = int(os.getenv("BRAIN_SMOKE_PORT", "8005"))
    base_url = f"http://127.0.0.1:{port}"
    token = "smoke-token"
    repo_root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory() as temp_dir:
        _check_bot_config(repo_root)
        env = os.environ.copy()
        env["BRAIN_SHARED_TOKEN"] = token
        env["BRAIN_TELEGRAM_KEY"] = token
        env["BRAIN_DB_PATH"] = str(Path(temp_dir) / "brain_smoke.db")
        env["PYTHONPATH"] = str(repo_root)

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "brain_api.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(repo_root),
            env=env,
        )
        try:
            _wait_for_health(base_url)

            headers = {"X-BRAIN-TOKEN": token}
            health = _request_json(f"{base_url}/health", headers={})
            if health.get("ok") is not True:
                raise RuntimeError("Unexpected /health response.")

            summary = _request_json(f"{base_url}/finance/summary", headers=headers)
            for key in ("today_date", "today_total", "month", "month_total", "top_categories", "latest"):
                if key not in summary:
                    raise RuntimeError(f"Missing key in /finance/summary: {key}")

            mood_last = _request_json(f"{base_url}/mood/last", headers=headers)
            if mood_last.get("ok") is not True:
                raise RuntimeError("Unexpected /mood/last response: ok != true")
            data = mood_last.get("data")
            if data is not None:
                for key in (
                    "id",
                    "ts_utc",
                    "local_date",
                    "slot",
                    "energy_level",
                    "mood_score",
                    "mood_text",
                    "did_thing",
                    "waste_spend",
                    "created_at",
                ):
                    if key not in data:
                        raise RuntimeError(f"Missing key in /mood/last data: {key}")

            print("SMOKE OK")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
