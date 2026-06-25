import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_monitor import windows_tray


if __name__ == "__main__":
    raise SystemExit(windows_tray.main())
