# win-automation

Windows desk tools for my [workflow-automation](https://github.com/vladio71/workflow-automation) app: a global `Pause` hotkey that toggles an always-on-top overlay with today's plan, `Ctrl+Pause` for the end-of-day handoff, and a morning task that asks the app to build the day's plan and opens it in a kiosk Chrome window. Python (pywebview, keyboard) and PowerShell, talks to the app over a token-protected API.

Два хоткеї поверх усього і ранковий автостарт для workflow-automation. Доповнення до `blocker` і `svc`.
Живе в `C:\repos\win-automation` (шлях до лога в `svc/services.json` розраховує на це).

| Клавіша | Що |
|---|---|
| `Pause` | показати/сховати оверлей: сторінка `/mini` апки (перший крок на сьогодні, список дня з галочками, "Start the day"). Без рамки, поверх усіх вікон, тягнеться мишею. Галочки справжні: та сама база, що в апці. |
| `Ctrl+Pause` | кінець дня: поле "завтра починаю з". `Enter` записує його в апку, `Esc` скасовує. Вечір після закритого дня вільний (ворота в `blocker`), тому більше нічого не робить; у `desk.json` → `end_of_day` можна увімкнути закриття програм і сон. |

Ранок (`morning.ps1`, 09:00 або при вході, якщо вже після 9): просить апку скласти план на сьогодні, якщо його
ще нема, і відкриває апку окремим вікном Chrome без адресного рядка. Перший крок із вчорашнього вечора
апка показує зверху на Today і на `/mini`, а в побажання до плану йде "Почати з: ...".

Клавіші, розмір оверлею, година ранку, що робити на кінець дня (`close`, `then`: `none` / `sleep` / `shutdown`) — у `desk.json`.

## Що потрібно з боку апки

Гілка з `/mini`, `/api/state`, `/api/handoff`, `/api/plan/generate` (див. патч у workflow-automation). Після деплою:

1. міграція на Neon: `npx prisma migrate deploy` з `DATABASE_URL` від Neon (як і раніше);
2. у Vercel → Environment Variables: `AUTOMATION_TOKEN` = довгий випадковий рядок (`openssl rand -hex 24`), передеплой;
3. той самий рядок одним рядком у `token.txt` поруч з `desk.py` (файл у `.gitignore`, в репо не йде).

Без токена ендпоінти відповідають 503, з чужим — 401.

## Встановлення

Python у PATH. У цій папці:

```
pip install -r requirements.txt
```

Створити `token.txt` з токеном. `desk.json` (`app_url`, клавіші) вже заповнений. Потім PowerShell від адміна:

```
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Він реєструє задачі `Desk` (при вході, живе весь час) і `DeskMorning` (09:00 і при вході) і одразу запускає `Desk`.
Натисни `Pause`: має з'явитись оверлей у правому верхньому куті.

Перевірити ранок, не чекаючи ранку: `schtasks /run /tn DeskMorning` (спрацює, якщо зараз після 9:00 і сьогодні ще не запускався;
маркер у `state\morning.txt`, видали його, щоб запустити ще раз).

У `svc/services.json` є рядок для `desk`, тож процес видно в панелі на :7777.

## Якщо щось не так

- `state\desk.log`, `state\morning.log`.
- Оверлей порожній або 503/401: перевір `token.txt` і `AUTOMATION_TOKEN` на Vercel.
- Хоткей не ловиться, коли активне вікно запущене від адміна (так працює Windows): клацни в звичайне вікно.
- Сон замість гібернації і навпаки: `SetSuspendState` робить те, що в системі ввімкнено; `powercfg /h off` вимикає гібернацію.
- Потрібен WebView2 (є на Windows 11 і на Windows 10 з Edge).
