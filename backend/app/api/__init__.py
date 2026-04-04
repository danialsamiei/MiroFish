"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
osint_bp = Blueprint('osint', __name__)
engine_bp = Blueprint('engine', __name__)
analyst_bp = Blueprint('analyst', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import osint  # noqa: E402, F401
from . import engine  # noqa: E402, F401
from . import analyst  # noqa: E402, F401

