"""
GridWise – PythonAnywhere WSGI entry point

PythonAnywhere serves apps through a WSGI interface.  This file wraps
the FastAPI ``app`` object from main.py so PythonAnywhere can load it.

After cloning the repo and installing dependencies, set the following
in the PythonAnywhere **Web** tab:

    WSGI configuration file:  /home/<you>/NITER_cHinoNaki-/wsgi.py
"""

import sys
import os

# Ensure the project directory is on the Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Expose the FastAPI app as 'application' (WSGI convention)
from main import app  # noqa: E402
application = app
