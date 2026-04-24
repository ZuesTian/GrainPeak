from __future__ import annotations

from app import GrainPeakApp, install_exception_hook


if __name__ == "__main__":
    install_exception_hook()
    app = GrainPeakApp()
    app.mainloop()
