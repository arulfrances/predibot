# Predibot web signal desk

Predibot is a browser-based Python app for reviewing manually pasted crypto signals. It shows the parsed pair and direction, the time the signal was added, and its stated expiry. **It does not create a market forecast, read Telegram automatically, connect to a trading account, or place orders.** Signals stay marked UNVERIFIED because no live crypto price, Telegram, or news connector is configured.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py app.py
```

Open `http://127.0.0.1:5000`. Try a sample such as `BTC/USD CALL 1m` or `ETHUSDT PUT 5m`. The UI is built with Flask, HTML templates, and CSS; `risk.py`, `verification.py`, and `execution.py` remain available as Python modules. The browser UI does not submit proposals to the execution layer.

Signals are held in a signed browser session cookie, capped at 20 entries, and are not durable storage. Do not put passwords, API keys, or Telegram session data in a signal. For hosting, use the generated `SECRET_KEY` in `render.yaml` and keep secrets in the host's environment settings.

## Deploy on Render

The included `render.yaml` configures a Python web service, installs `requirements.txt`, and runs `gunicorn app:app`. To deploy, push this project to a GitHub or GitLab repository, then in Render choose **New → Blueprint** and connect that repository. Review the service settings and deploy. Render supplies the public URL when the build finishes. You can also create a Web Service manually with build command `pip install -r requirements.txt` and start command `gunicorn app:app`.

Render's free web services can spin down after inactivity, so the first page load after a quiet period can be delayed. This app has no continuous worker and its browser-session signal list is not persistent storage.

## Sources and next connections

- Crypto market data needs a selected public provider, freshness checks, and explicit source/time labels before a prediction model can be developed or evaluated.
- Telegram automation needs an officially supported bot/client setup and credentials kept on the server. The current app accepts pasted messages only.
- Pocket Option is linked only as an external site. This app does not log in to it or place trades. Its [Public Offer](https://pocketoption.com/en/public-offer/) reserves the right to cancel or revise trades made with unauthorized bot software.

The current verification module is a fail-closed evidence gate, not a calibrated win-probability model. A passing evidence check would not guarantee an outcome or justify an automatic trade.
