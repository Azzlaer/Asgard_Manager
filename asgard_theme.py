from __future__ import annotations

import math
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from common import APP_DIR


PALETTE = {
    "void": "#050101",
    "surface": "#0B0304",
    "surface2": "#120507",
    "panel": "#19080B",
    "panel_hover": "#2A0C12",
    "panel_active": "#3B0E17",
    "accent": "#C8102E",
    "accent_hot": "#FF1F46",
    "accent_soft": "#FF7A8E",
    "accent_dark": "#71091B",
    # Alias conservados para módulos antiguos. Ya apuntan a la paleta roja.
    "violet": "#C8102E",
    "violet2": "#FF7A8E",
    "cyan": "#FF1F46",
    "cyan2": "#FF9AA9",
    "text": "#FFF4F4",
    "muted": "#C9A8AE",
    "dim": "#80656A",
    "border": "#4B1118",
    "danger": "#FF294D",
    "warning": "#FFB020",
    "success": "#45D483",
}


def apply_void_theme(root: tk.Misc) -> ttk.Style:
    """Aplica el tema Crimson Void a ttk, Tk clásico y menús.

    Se configuran explícitamente los estados readonly/disabled/selected para
    evitar texto negro sobre fondo negro en ciertos builds de Windows/Tk.
    """
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=PALETTE["void"])
    try:
        root.tk_setPalette(
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            activeBackground=PALETTE["panel_hover"],
            activeForeground=PALETTE["text"],
            selectBackground=PALETTE["accent"],
            selectForeground="#FFFFFF",
        )
    except tk.TclError:
        pass

    # Tk clásico: menús, textos, listbox y diálogos que no obedecen ttk.
    for pattern, value in {
        "*Menu.background": PALETTE["surface2"],
        "*Menu.foreground": PALETTE["text"],
        "*Menu.activeBackground": PALETTE["accent"],
        "*Menu.activeForeground": "#FFFFFF",
        "*Menu.disabledForeground": PALETTE["dim"],
        "*Menu.selectColor": PALETTE["accent_hot"],
        "*Text.background": PALETTE["void"],
        "*Text.foreground": PALETTE["text"],
        "*Text.insertBackground": "#FFFFFF",
        "*Text.selectBackground": PALETTE["accent_dark"],
        "*Text.selectForeground": "#FFFFFF",
        "*Listbox.background": PALETTE["surface2"],
        "*Listbox.foreground": PALETTE["text"],
        "*Listbox.selectBackground": PALETTE["accent"],
        "*Listbox.selectForeground": "#FFFFFF",
        "*TCombobox*Listbox.background": PALETTE["surface2"],
        "*TCombobox*Listbox.foreground": PALETTE["text"],
        "*TCombobox*Listbox.selectBackground": PALETTE["accent"],
        "*TCombobox*Listbox.selectForeground": "#FFFFFF",
    }.items():
        root.option_add(pattern, value)

    style.configure(
        ".",
        font=("Segoe UI", 10),
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["void"],
        troughcolor=PALETTE["void"],
        focuscolor=PALETTE["accent_hot"],
    )

    style.configure("TFrame", background=PALETTE["surface"])
    style.configure("Void.TFrame", background=PALETTE["void"])
    style.configure("Panel.TFrame", background=PALETTE["panel"], relief="flat")
    style.configure("Card.TFrame", background=PALETTE["panel"], relief="flat")
    style.configure("TLabel", background=PALETTE["surface"], foreground=PALETTE["text"])
    style.configure("Muted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"])
    style.configure("Status.TLabel", background=PALETTE["surface2"], foreground=PALETTE["accent_soft"], padding=(8, 4))
    style.configure("Success.TLabel", foreground=PALETTE["success"])
    style.configure("Warning.TLabel", foreground=PALETTE["warning"])
    style.configure("Danger.TLabel", foreground=PALETTE["danger"])
    style.configure("Hero.TLabel", background=PALETTE["void"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 22))
    style.configure("HeroSub.TLabel", background=PALETTE["void"], foreground=PALETTE["accent_soft"], font=("Segoe UI", 10))

    style.configure(
        "TLabelframe",
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=PALETTE["surface"],
        foreground=PALETTE["accent_soft"],
        font=("Segoe UI Semibold", 10),
    )

    style.configure(
        "TEntry",
        fieldbackground=PALETTE["surface2"],
        background=PALETTE["surface2"],
        foreground=PALETTE["text"],
        insertcolor="#FFFFFF",
        bordercolor=PALETTE["border"],
        padding=(8, 6),
    )
    style.map(
        "TEntry",
        fieldbackground=[("readonly", PALETTE["panel"]), ("disabled", PALETTE["surface"])],
        foreground=[("readonly", PALETTE["text"]), ("disabled", PALETTE["dim"])],
        bordercolor=[("focus", PALETTE["accent_hot"])],
    )
    style.configure(
        "TCombobox",
        fieldbackground=PALETTE["surface2"],
        background=PALETTE["panel"],
        foreground=PALETTE["text"],
        arrowcolor=PALETTE["accent_soft"],
        bordercolor=PALETTE["border"],
        padding=(7, 5),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PALETTE["surface2"]), ("disabled", PALETTE["surface"])],
        foreground=[("readonly", PALETTE["text"]), ("disabled", PALETTE["dim"])],
        selectbackground=[("readonly", PALETTE["surface2"])],
        selectforeground=[("readonly", PALETTE["text"])],
        bordercolor=[("focus", PALETTE["accent_hot"])],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=PALETTE["surface2"],
        foreground=PALETTE["text"],
        arrowcolor=PALETTE["accent_soft"],
        bordercolor=PALETTE["border"],
    )
    style.map("TSpinbox", foreground=[("disabled", PALETTE["dim"])])

    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, background=PALETTE["surface"], foreground=PALETTE["text"], indicatorcolor=PALETTE["surface2"])
        style.map(
            widget,
            background=[("active", PALETTE["surface"])],
            foreground=[("disabled", PALETTE["dim"]), ("active", PALETTE["text"])],
            indicatorcolor=[("selected", PALETTE["accent"]), ("active", PALETTE["panel_hover"])],
        )

    style.configure(
        "TButton",
        background=PALETTE["panel"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        padding=(12, 7),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("active", PALETTE["panel_hover"]), ("pressed", PALETTE["panel_active"])],
        foreground=[("disabled", PALETTE["dim"]), ("active", "#FFFFFF")],
        bordercolor=[("focus", PALETTE["accent_hot"]), ("active", PALETTE["accent"])],
    )
    style.configure("Accent.TButton", background=PALETTE["accent"], foreground="#FFFFFF", bordercolor=PALETTE["accent_hot"], padding=(14, 8), font=("Segoe UI Semibold", 10))
    style.map("Accent.TButton", background=[("active", PALETTE["accent_hot"]), ("pressed", PALETTE["accent_dark"])])
    style.configure("Danger.TButton", background=PALETTE["accent_dark"], foreground="#FFE9ED", bordercolor=PALETTE["danger"], padding=(12, 7))
    style.map("Danger.TButton", background=[("active", "#9F1239"), ("pressed", "#6F0A20")])

    style.configure("Treeview", background=PALETTE["surface2"], fieldbackground=PALETTE["surface2"], foreground=PALETTE["text"], rowheight=30, borderwidth=0)
    style.configure("Treeview.Heading", background=PALETTE["panel"], foreground=PALETTE["accent_soft"], font=("Segoe UI Semibold", 10), relief="flat")
    style.map(
        "Treeview",
        background=[("selected", PALETTE["accent_dark"])],
        foreground=[("selected", "#FFFFFF")],
    )
    style.map("Treeview.Heading", background=[("active", PALETTE["panel_hover"])], foreground=[("active", "#FFFFFF")])

    style.configure("TNotebook", background=PALETTE["surface"], borderwidth=0)
    style.configure("TNotebook.Tab", background=PALETTE["panel"], foreground=PALETTE["muted"], padding=(14, 8), borderwidth=0)
    style.map(
        "TNotebook.Tab",
        background=[("selected", PALETTE["accent_dark"]), ("active", PALETTE["panel_hover"])],
        foreground=[("selected", "#FFFFFF"), ("active", PALETTE["text"])],
    )
    style.configure("TPanedwindow", background=PALETTE["border"], sashwidth=5)
    style.configure("TScrollbar", background=PALETTE["panel"], troughcolor=PALETTE["void"], arrowcolor=PALETTE["accent_soft"], bordercolor=PALETTE["void"])
    style.map("TScrollbar", background=[("active", PALETTE["accent_dark"])])
    style.configure("TSeparator", background=PALETTE["border"])

    style.configure("CardTitle.TLabel", background=PALETTE["panel"], foreground=PALETTE["muted"], font=("Segoe UI", 9))
    style.configure("CardValue.TLabel", background=PALETTE["panel"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 16))
    style.configure("CardValueSmall.TLabel", background=PALETTE["panel"], foreground=PALETTE["text"], font=("Segoe UI Semibold", 11))
    return style


class VoidAvatarFace(tk.Canvas):
    """Logo del panel cargado desde Assets/void_avatar_user.png.

    Usa exactamente la imagen proporcionada por el usuario. El dibujo antiguo se
    mantiene solo como respaldo si el recurso falta o Tk no puede abrirlo.
    """

    def __init__(self, master, size=72, **kwargs):
        super().__init__(
            master,
            width=size,
            height=size,
            highlightthickness=0,
            bd=0,
            bg=PALETTE["void"],
            **kwargs,
        )
        self._size = size
        self._photo = None
        self._source_photo = None
        if not self._load_user_logo():
            self._draw_fallback()

    @staticmethod
    def asset_path():
        """Resolve the real PNG from the PyInstaller bundle or portable Assets."""
        candidates = []
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.append(Path(bundle_root) / "Assets" / "void_avatar_user.png")
        candidates.append(APP_DIR / "Assets" / "void_avatar_user.png")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[-1]

    def _load_user_logo(self):
        try:
            source = tk.PhotoImage(file=str(self.asset_path()))
            self._source_photo = source
            width = max(1, source.width())
            height = max(1, source.height())
            factor = max(1, int(max(width, height) / max(1, self._size)))
            photo = source.subsample(factor, factor) if factor > 1 else source
            self._photo = photo
            self.delete("all")
            self.create_image(self._size / 2, self._size / 2, image=photo, anchor="center")
            return True
        except (tk.TclError, OSError):
            return False

    def _draw_fallback(self):
        # Never show the obsolete procedural face again. A neutral ASGARD mark
        # makes a missing resource obvious instead of looking like the old logo.
        self.delete("all")
        s = self._size
        self.create_oval(4, 4, s - 4, s - 4, fill=PALETTE["void"], outline=PALETTE["accent_hot"], width=3)
        self.create_text(s / 2, s / 2, text="A", fill="#FFFFFF", font=("Segoe UI Black", max(16, int(s * 0.42))))


def load_window_logo():
    """Carga el mismo recurso para el icono de la ventana principal."""
    try:
        return tk.PhotoImage(file=str(VoidAvatarFace.asset_path()))
    except (tk.TclError, OSError):
        return None


# Compatibilidad con el nombre usado por versiones anteriores.
VoidSigil = VoidAvatarFace
