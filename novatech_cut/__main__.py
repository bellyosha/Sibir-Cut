from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from .selftest import main as selftest_main
        return selftest_main()

    from .app import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
