"""The General Classification Annotator as a playground tab (and later an OpenPara add-on): a Qt window in app/ rebuilt from the
Tkinter program of the General-Classification-Annotator repository. app/ holds the toolkit-free code of the original unchanged
(annotator_core, share_zip, web_mode, model_* ...) plus the Qt window (annotator_window / annotator_canvas / annotator_dialogs / qtk).
"""
import importlib.util
import os
import sys

from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app")
# (import name, pip name, needed for, required)
PACKAGES = [("PIL", "pillow", "everything", True), ("numpy", "numpy", "everything", True),
            ("cv2", "opencv-python", "video import and the AI models", True),
            ("qrcode", "qrcode", "the QR code for the tablet page (the address and code work without it)", False),
            ("torch", "torch", "AI pre-labeling (large)", False), ("torchvision", "torchvision", "AI pre-labeling", False),
            ("ultralytics", "ultralytics", "the YOLO models", False)]


def missing(required_only=False):
    return [(i, p, why, req) for i, p, why, req in PACKAGES if importlib.util.find_spec(i) is None and (req or not required_only)]


def make_tab(path=None):
    """The annotator window, or a page saying which packages to install when a required one is missing.
    With a project folder it opens that project (a folder with its dataset inside); without one it starts a new project in a temporary
    folder, which is saved to a project folder of its own the first time something is imported into it (or with Save)."""
    if APP not in sys.path:
        sys.path.insert(0, APP)
    need = missing(required_only=True)
    if need:
        return MissingPackages(need)
    import annotator_window as aw
    if path:
        os.makedirs(path, exist_ok=True)
        return aw.AnnotatorWindow(path)
    return aw.AnnotatorWindow(aw.untitled_dir(), temp=True)


class MissingPackages(QWidget):
    def __init__(self, need, text=None):
        super().__init__()
        self.path = None
        self.host = None
        lay = QVBoxLayout(self)
        msg = text or ("The annotator needs these packages first: " + ", ".join(p for _i, p, _w, _r in need) + "\n\nInstall:\n    pip install "
                       + " ".join(p for _i, p, _w, _r in need) + "\n\nThe AI models also need torch, torchvision and ultralytics "
                       f"(see {os.path.join(HERE, 'requirements.txt')}).")
        lab = QLabel(msg)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lay.addStretch(1)

    def title(self):
        return "Annotator"
