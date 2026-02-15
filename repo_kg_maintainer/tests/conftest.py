from __future__ import annotations

import sys
from pathlib import Path


REPO_KG_MAINTAINER_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_KG_MAINTAINER_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_KG_MAINTAINER_ROOT))
