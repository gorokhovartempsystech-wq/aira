"""Fixed isolated minimal child entry; engine import happens after the gate."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).absolute().parents[3]))
    from ara.docx_analysis_worker.macos._child_bootstrap import main

    sys.exit(main(sys.argv[1:]))
