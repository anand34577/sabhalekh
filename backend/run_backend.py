"""PyInstaller / development entry point for the backend sidecar."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from sabhalekh.main import main

    main()
