# GridWise – PythonAnywhere Deployment Guide

## Overview

This guide walks you through deploying the GridWise FastAPI backend to
[PythonAnywhere](https://www.pythonanywhere.com) using the `main` branch
of `https://github.com/kn8trix/NITER_cHinoNaki-.git`.

PythonAnywhere uses a **WSGI** server, so a thin `wsgi.py` wrapper is
provided to expose the FastAPI `app`.

---

## Prerequisites

- A PythonAnywhere account (Free tier works; paid tiers give more CPU/RAM)
- Your repository already pushed to GitHub

---

## Step 1 — Clone the Repository

Open a **Bash console** on PythonAnywhere (`Consoles` tab → `Bash`).

```bash
# Clone your repo into the home directory
cd ~
git clone https://github.com/kn8trix/NITER_cHinoNaki-.git

# Verify the files
ls NITER_cHinoNaki-/
# Expected: main.py  optimizer.py  parser.py  requirements.txt  wsgi.py  ...
```

---

## Step 2 — Create and Activate a Virtual Environment

PythonAnywhere recommends per-app virtual environments.

```bash
cd ~/NITER_cHinoNaki-

# Create a venv (Python 3.10+ required for the Pydantic type hints)
python3.10 -m venv venv

# Activate it
source venv/bin/activate

# Confirm you're inside the venv
which python
# Should output: /home/<your-username>/NITER_cHinoNaki-/venv/bin/python
```

> **Note:** PythonAnywhere may offer Python 3.10, 3.11, or 3.12 depending on
> your plan.  Use whichever is available — just make sure it is ≥ 3.10.

---

## Step 3 — Install Dependencies

```bash
# With the venv active
pip install --upgrade pip
pip install -r requirements.txt
```

Verify key packages installed:

```bash
pip show fastapi pulp uvicorn
```

You should see version info for all three.

---

## Step 4 — Set Environment Variables

The parser needs an OpenRouter API key.  Set it in your Bash console session
and also persist it for the web app:

```bash
# Export for the current console session (for testing)
export OPENROUTER_API_KEY="sk-or-v1-xxxxxxxxxxxx"
```

To persist it for the web app, see **Step 6** below (set it in the
PythonAnywhere **Web** tab environment variables section).

---

## Step 5 — Configure the Web App (Web Tab)

1. Go to the **Web** tab on your PythonAnywhere dashboard.
2. Click **"Add a new web app"**.
3. Select **Manual configuration** (not "Nginx" — you want the Python WSGI server).
4. Choose the Python version that matches your venv (e.g., **Python 3.10**).

### 5a. Set the WSGI Configuration File

In the Web tab, find **"WSGI configuration file:"** — click the link (it opens
an editor).  Replace its contents with:

```python
# GridWise – PythonAnywhere WSGI Configuration
# See: https://help.pythonanywhere.com/pages/AnySystemWSGIConfiguration/

import sys
import os

# Point to the project directory
project_home = '/home/<your-username>/NITER_cHinoNaki-'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Activate the virtualenv for this process
virtualenv = os.path.join(project_home, 'venv')
if os.path.exists(os.path.join(virtualenv, 'bin')):
    activate_this = os.path.join(virtualenv, 'bin', 'activate_this.py')
else:
    activate_this = os.path.join(virtualenv, 'Scripts', 'activate_this.py')

if os.path.exists(activate_this):
    exec(open(activate_this).read(), dict(__file__=activate_this))
else:
    # Fallback: prepend venv site-packages manually
    site_packages = os.path.join(
        virtualenv, 'lib',
        f'python3.{sys.version_info.minor}', 'site-packages'
    )
    sys.path.insert(0, site_packages)

from main import app
application = app
```

> **Replace `<your-username>`** with your actual PythonAnywhere username.

### 5b. Set the Working Directory

In the Web tab, set **Working directory** to:

```
/home/<your-username>/NITER_cHinoNaki-
```

---

## Step 6 — Set Environment Variables

In the **Web** tab, scroll to the **Environment variables** section and add:

| Key                       | Value                          |
|---------------------------|--------------------------------|
| `OPENROUTER_API_KEY`      | `sk-or-v1-xxxxxxxxxxxx`       |

---

## Step 7 — Reload the Web App

Back at the top of the **Web** tab, click the green **"Reload"** button.

---

## Step 8 — Verify the Deployment

### 8a. Check the error log

If reload shows errors, click **"Error log"** in the Web tab to inspect.

### 8b. Test the health endpoint

Open a Bash console and run:

```bash
curl https://<your-username>.pythonanywhere.com/health
```

Expected response:

```json
{"status": "ok", "service": "gridwise-optimizer"}
```

### 8c. Test the optimize endpoint

```bash
curl -X POST https://<your-username>.pythonanywhere.com/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "initial_energy": 50.0,
    "battery_capacity": 100.0,
    "max_c_rate": 0.5,
    "demand_forecast": [50,50,48,48,45,55,70,80,85,80,75,70,70,65,60,55,60,70,80,75,60,50,48,50],
    "solar_forecast": [0,0,0,0,0,2,5,10,15,18,20,22,22,20,18,15,10,5,2,0,0,0,0,0],
    "tariffs": [0.08,0.08,0.08,0.08,0.08,0.08,0.10,0.12,0.15,0.18,0.20,0.22,0.25,0.22,0.20,0.18,0.15,0.12,0.10,0.10,0.08,0.08,0.08,0.08],
    "operator_notes": "No charging from hour 12 to 14. Keep at least 20% battery reserve."
  }'
```

You should get back a JSON payload with `"status": "Optimal"` and a full
24-hour schedule.

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'pulp'"

Make sure you are activating the correct virtualenv in the WSGI file.
PythonAnywhere sometimes defaults to a different Python version.

### "Application not responding" / 502 Bad Gateway

1. Check the **Error log** in the Web tab.
2. Ensure the `reload` button was clicked after every change.
3. Confirm `wsgi.py` loads without errors:

```bash
cd ~/NITER_cHinoNaki-
source venv/bin/activate
python -c "from wsgi import application; print('OK')"
```

### Solver errors ("Infeasible")

The LP solver may return infeasible if operator constraints are
contradictory (e.g., no charge + no discharge for all 24 hours with
depleting demand).  The optimizer gracefully returns a status message
in this case.

### CORS issues

If you're calling the API from a browser-based frontend, add CORS
middleware to `main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## File Reference

| File            | Purpose                                      |
|-----------------|----------------------------------------------|
| `main.py`       | FastAPI app with `/optimize` and `/health`   |
| `parser.py`     | OpenRouter operator-notes parser             |
| `optimizer.py`  | PuLP 24-hour LP optimizer                   |
| `requirements.txt` | Python dependencies                      |
| `wsgi.py`       | WSGI entry point for PythonAnywhere          |
| `DEPLOY.md`     | This deployment guide                        |
