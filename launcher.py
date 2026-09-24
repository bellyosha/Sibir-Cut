from __future__ import annotations
import sys

def main() -> int:
    if "--self-test" in sys.argv:
        from novatech_cut.selftest import main as selftest_main
        return selftest_main()
    if "--ui-self-test" in sys.argv:
        try:
            from novatech_cut.app import calibration_gui_self_test
            calibration_gui_self_test()
            return 0
        except Exception:
            import traceback, tempfile
            from pathlib import Path
            tb=traceback.format_exc()
            try:(Path(tempfile.gettempdir())/'novatech-cut-ui-selftest-error.txt').write_text(tb,encoding='utf-8')
            except Exception:pass
            return 3
    from novatech_cut.app import main as gui_main
    gui_main()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
