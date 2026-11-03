"""Imports every module's ORM models so ``Base.metadata`` is complete.

Each module owns its line here; add a line when you add a new ``models.py``.
"""

from app.analysis import models as analysis_models  # noqa: F401
from app.core import audit  # noqa: F401
from app.eln import models as eln_models  # noqa: F401
from app.memory import models as memory_models  # noqa: F401
from app.partner import models as partner_models  # noqa: F401
