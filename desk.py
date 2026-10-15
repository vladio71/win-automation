"""
desk: два хоткеї поверх усього (Windows).

  Pause        показати/сховати оверлей: сторінка /mini апки (перший крок, список дня з галочками,
               "Start the day"). Вікно без рамки, поверх усіх вікон, можна тягнути мишею.
  Ctrl+Pause   кінець дня: вікно з полем "завтра починаю з". Enter -> запис в апку (/api/handoff).
               Esc -> нічого не сталось. За бажанням (desk.json -> end_of_day) ще закриває програми і присипляє.

Клавіші, розмір оверлею, що закривати і що робити потім - у desk.json поруч.
Токен апки - у token.txt поруч (у .gitignore).
Запускається Task Scheduler'ом при вході (install.ps1), без консолі (pythonw). Лог: state\\desk.log.

Вікна створюються при першому натисканні, а не на старті: створене прихованим вікно WebView2 на Windows
лишалось білим. Щоб webview.start() було з чим стартувати, на старті є одне порожнє вікно 1x1 за екраном.

Залежності: pip install -r requirements.txt   (pywebview, keyboard, requests; на Windows потрібен WebView2,
він є на Win11 і на Win10 з Edge).
"""

import json
import logging
import os
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "desk.json")
# Токен окремо від конфіга, бо desk.json у репо, а token.txt у .gitignore
TOKEN_PATH = os.path.join(HERE, "token.txt")
STATE_DIR = os.path.join(HERE, "state")
LOG_PATH = os.path.join(STATE_DIR, "desk.log")

log = logging.getLogger("desk")


def setup_logging() -> None:
    """Під pythonw немає консолі, тому все у файл, інакше падіння ніхто не побачить.
    Хендлер на root-логері: помилки pywebview (логер 'pywebview') теж потрапляють сюди."""
    os.makedirs(STATE_DIR, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


setup_logging()

# Третьосторонні імпорти після логера: якщо пакета нема, причина буде в desk.log, а не в порожнечі.
try:
    import keyboard
    import requests
    import webview
except ImportError as e:
    log.error("import failed: %s. Run: pip install -r requirements.txt", e)
    raise


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_token() -> str:
    """AUTOMATION_TOKEN з Vercel, один рядок у token.txt поруч зі скриптом."""
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            token = f.read().strip()
    except FileNotFoundError:
        token = ""
    if not token:
        log.error("token.txt порожній або відсутній: поклади туди AUTOMATION_TOKEN з Vercel")
    return token


# ---------------------------------------------------------------- вікно "кінець дня" (локальний HTML)

END_OF_DAY_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; padding: 18px 20px 16px; font: 14px/1.45 "Segoe UI", system-ui, sans-serif;
         background: #1b1b1b; color: #ececec; user-select: none; }
  @media (prefers-color-scheme: light) { body { background: #fafafa; color: #222; } }
  .today { font-size: 12px; opacity: .55; min-height: 16px; }
  .label { margin-top: 8px; font-weight: 600; }
  input { width: 100%; box-sizing: border-box; margin-top: 8px; padding: 9px 11px; font: inherit;
          border: 1px solid #555; border-radius: 6px; background: transparent; color: inherit; }
  input:focus { outline: 2px solid #4a7cff; border-color: transparent; }
  .hint { margin-top: 10px; font-size: 12px; opacity: .55; }
  .err { margin-top: 8px; font-size: 12px; color: #ff6b6b; min-height: 16px; }
</style></head>
<body>
  <div class="today" id="today"></div>
  <div class="label">Завтра починаю з</div>
  <input id="f" maxlength="200" placeholder="одна річ, з якої почнеться ранок (можна порожнє)">
  <div class="hint">Enter: записати &nbsp;·&nbsp; Esc: скасувати</div>
  <div class="err" id="err"></div>
<script>
  const f = document.getElementById('f');
  const err = document.getElementById('err');
  const today = document.getElementById('today');
  function reset() {
    f.value = ''; err.textContent = ''; today.textContent = '';
    setTimeout(() => f.focus(), 60);
    pywebview.api.state().then((s) => {
      if (!s.ok) { err.textContent = s.error; return; }
      today.textContent = 'Сьогодні ' + s.done + '/' + s.total + (s.allDone ? ' · усе закрито' : '');
    }).catch(() => {});
  }
  async function submit() {
    err.textContent = '…';
    const r = await pywebview.api.submit(f.value);
    err.textContent = r.ok ? '' : r.error;
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); pywebview.api.cancel(); }
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
  });
  window.addEventListener('pywebviewready', reset);
</script>
</body></html>"""


class Desk:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.app_url = str(cfg["app_url"]).rstrip("/")
        self.headers = {"x-automation-token": load_token()}
        self.overlay: webview.Window | None = None
        self.end_window: webview.Window | None = None
        self.overlay_visible = False
        self.end_visible = False
        # evaluate_js чекає, поки сторінка завантажиться; шлемо JS тільки після події loaded
        self.end_loaded = False
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- апка

    def get_state(self) -> dict:
        try:
            r = requests.get(f"{self.app_url}/api/state", headers=self.headers, timeout=8)
            r.raise_for_status()
            data = r.json()
            data["ok"] = True
            return data
        except Exception as e:  # мережа, 401, 503: показуємо причину, не падаємо
            log.warning("state failed: %s", e)
            return {"ok": False, "error": str(e)}

    def post_handoff(self, text: str) -> tuple[bool, str]:
        try:
            r = requests.post(f"{self.app_url}/api/handoff", json={"firstStep": text}, headers=self.headers, timeout=10)
            if r.status_code != 200:
                return False, f"апка відповіла {r.status_code}: {r.text[:200]}"
            return True, ""
        except Exception as e:
            return False, f"не достукався до апки: {e}"

    # ---------------------------------------------------------------- оверлей

    def toggle_overlay(self) -> None:
        with self.lock:
            if self.overlay is None:
                self.overlay = self._create_overlay()
                self.overlay_visible = True
                return
            if self.overlay_visible:
                self.overlay.hide()
                self.overlay_visible = False
                return
            try:
                self.overlay.evaluate_js("location.reload()")  # свіжі галочки, якщо щось міняв в апці
            except Exception as e:
                log.warning("overlay reload: %s", e)
            self.overlay.show()
            self.overlay_visible = True

    def _create_overlay(self) -> webview.Window:
        ov = self.cfg.get("overlay", {})
        width = int(ov.get("width", 460))
        height = int(ov.get("height", 640))
        margin = int(ov.get("margin", 24))
        screen = webview.screens[0]
        window = webview.create_window(
            "desk", url=f"{self.app_url}/mini",
            width=width, height=height, x=screen.width - width - margin, y=margin + 40,
            frameless=True, on_top=True, easy_drag=True,
        )

        def closed() -> None:  # Alt+F4: наступний Pause створить вікно заново
            with self.lock:
                self.overlay = None
                self.overlay_visible = False

        window.events.closed += closed
        log.info("overlay created")
        return window

    # ---------------------------------------------------------------- кінець дня

    def show_end_of_day(self) -> None:
        with self.lock:
            if self.end_visible:
                return
            if self.end_window is None:
                self.end_window = self._create_end_window()
                self.end_visible = True
                return
            if self.end_loaded:
                try:
                    self.end_window.evaluate_js("reset()")
                except Exception as e:
                    log.warning("end-of-day reset: %s", e)
            self.end_window.show()
            self.end_visible = True

    def _create_end_window(self) -> webview.Window:
        screen = webview.screens[0]
        window = webview.create_window(
            "end of day", html=END_OF_DAY_HTML, js_api=EndOfDayApi(self),
            width=520, height=190, x=int((screen.width - 520) / 2), y=int(screen.height * 0.3),
            frameless=True, on_top=True, easy_drag=True,
        )

        def loaded() -> None:
            self.end_loaded = True

        def closed() -> None:
            with self.lock:
                self.end_window = None
                self.end_visible = False
                self.end_loaded = False

        window.events.loaded += loaded
        window.events.closed += closed
        log.info("end-of-day window created")
        return window

    def hide_end_of_day(self) -> None:
        with self.lock:
            if self.end_window is not None and self.end_visible:
                self.end_window.hide()
                self.end_visible = False

    def finish_day(self) -> None:
        """Закрити вказані програми (м'яко, без /F: незбережене у VS Code лишиться відкритим), потім сон/вимкнення."""
        eod = self.cfg.get("end_of_day", {})
        if self.overlay_visible:
            self.toggle_overlay()
        for image in eod.get("close", []):
            subprocess.run(["taskkill", "/IM", image], capture_output=True)
            log.info("closed %s", image)
        then = str(eod.get("then", "none"))
        if then == "none":
            return
        time.sleep(6)  # дати програмам закритись
        if then == "sleep":
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif then == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "30"])
        log.info("end of day: %s", then)


class EndOfDayApi:
    """Методи, які викликає JS у вікні "кінець дня" (pywebview.api.*)."""

    def __init__(self, desk: Desk):
        self.desk = desk

    def state(self) -> dict:
        return self.desk.get_state()

    def submit(self, text: str) -> dict:
        text = (text or "").strip()
        if text:  # порожнє поле = не чіпати те, що вже записано
            ok, error = self.desk.post_handoff(text)
            if not ok:
                log.warning("handoff failed: %s", error)
                return {"ok": False, "error": error}
            log.info("handoff saved: %s", text)
        self.desk.hide_end_of_day()
        threading.Thread(target=self.desk.finish_day, daemon=True).start()
        return {"ok": True}

    def cancel(self) -> None:
        self.desk.hide_end_of_day()


class Debounced:
    """Хоткей, який не спрацьовує двічі поспіль: деякі клавіші шлють подвійні події."""

    def __init__(self, action):
        self.action = action
        self.last_at = 0.0

    def __call__(self) -> None:
        now = time.monotonic()
        if now - self.last_at < 0.4:
            return
        self.last_at = now
        try:
            self.action()
        except Exception:
            log.exception("hotkey action failed")


def after_start(desk: Desk, anchor: webview.Window) -> None:
    """Викликається pywebview у своєму потоці після старту GUI: ховаємо вікно-якір, вішаємо хоткеї."""
    try:
        anchor.hide()
    except Exception as e:
        log.warning("anchor hide: %s", e)
    hk = desk.cfg.get("hotkeys", {})
    overlay_key = str(hk.get("overlay", "pause"))
    end_key = str(hk.get("end_of_day", "ctrl+pause"))
    bind(overlay_key, Debounced(desk.toggle_overlay))
    bind(end_key, Debounced(desk.show_end_of_day))
    log.info("hotkeys: overlay=%s end_of_day=%s", overlay_key, end_key)


# Ctrl+Pause Windows віддає не як Ctrl + Pause, а як окрему клавішу Break (VK_CANCEL),
# тому для "ctrl+pause" вішаємо ще й "ctrl+break" і "break". Одна дія за раз завдяки Debounced.
HOTKEY_ALIASES: dict[str, list[str]] = {
    "ctrl+pause": ["ctrl+pause", "ctrl+break", "break"],
}


def bind(hotkey: str, action) -> None:
    for name in HOTKEY_ALIASES.get(hotkey.lower(), [hotkey]):
        try:
            keyboard.add_hotkey(name, action)
        except Exception as e:  # назва невідома цій розкладці: пропускаємо, решта аліасів лишається
            log.warning("hotkey %s not bound: %s", name, e)


def main() -> None:
    cfg = load_config()
    desk = Desk(cfg)
    # webview.start() вимагає хоч одне вікно: порожнє 1x1 за межами екрана, після старту ховається
    anchor = webview.create_window("desk-anchor", html="<html></html>", width=1, height=1, x=-4000, y=-4000,
                                   frameless=True, hidden=True)
    log.info("desk started, pid %s, app %s", os.getpid(), desk.app_url)
    webview.start(after_start, (desk, anchor))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("desk crashed")  # Task Scheduler перезапустить через хвилину
        raise
