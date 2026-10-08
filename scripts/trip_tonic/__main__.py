"""支持 `python -m scripts.trip_tonic` 与 `python -m trip_tonic` 入口。"""

import sys

from .cli import main

sys.exit(main())
