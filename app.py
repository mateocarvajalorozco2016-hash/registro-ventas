import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

# -----------------------------------------------------------------------------
# Rutas persistentes: en PyInstaller --onefile NO usamos la carpeta temporal.
# Todo lo que el usuario crea queda junto al EXE, dentro de datos/.
# -----------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent
RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", BASE))

DATA = BASE / "datos"
PRODUCTS = DATA / "productos"
MONEY = DATA / "dinero"
DEFAULT_MONEY = RESOURCE_BASE / "datos" / "dinero_predeterminado"
DB = DATA / "ventas.db"
CONFIG = DATA / "configuracion.json"
for folder in (DATA, PRODUCTS, MONEY):
    folder.mkdir(parents=True, exist_ok=True)

DENOMINATIONS = [1000, 2000, 5000, 10000, 20000, 50000, 100000]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def money(value):
    return "$" + f"{int(value):,}".replace(",", ".")


def format_number(value):
    value = int(value or 0)
    return f"{value:,}".replace(",", ".")


def parse_money(text):
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else 0


def normalize(text):
    return " ".join(str(text).casefold().strip().split())


def database():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("""CREATE TABLE IF NOT EXISTS categorias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS productos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT NOT NULL,
        precio INTEGER NOT NULL DEFAULT 0,
        imagen TEXT NOT NULL DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ventas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        total INTEGER NOT NULL,
        recibido INTEGER NOT NULL,
        cambio INTEGER NOT NULL,
        descuento INTEGER NOT NULL DEFAULT 0
    )""")
    # Compatibilidad con bases de datos creadas en versiones anteriores.
    columnas_ventas = [row[1] for row in c.execute("PRAGMA table_info(ventas)").fetchall()]
    if "descuento" not in columnas_ventas:
        c.execute("ALTER TABLE ventas ADD COLUMN descuento INTEGER NOT NULL DEFAULT 0")
    c.execute("""CREATE TABLE IF NOT EXISTS detalle(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id INTEGER NOT NULL,
        nombre TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        precio INTEGER NOT NULL,
        FOREIGN KEY(venta_id) REFERENCES ventas(id) ON DELETE CASCADE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS clientes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
        telefono TEXT NOT NULL DEFAULT '',
        notas TEXT NOT NULL DEFAULT '',
        creado TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS movimientos_clientes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('FIADO','ABONO')),
        monto INTEGER NOT NULL,
        concepto TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
    )""")
    c.commit()
    return c


def load_config():
    default = {"negocio": "MI NEGOCIO", "dinero": {}}
    try:
        if CONFIG.exists():
            raw = json.loads(CONFIG.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                default["negocio"] = str(raw.get("negocio") or "MI NEGOCIO")
                default["dinero"] = raw.get("dinero") if isinstance(raw.get("dinero"), dict) else {}
    except Exception:
        pass
    return default


def save_config(config):
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_image(source, destination, prefix):
    if not source:
        return ""
    src = Path(source)
    if not src.exists() or src.suffix.lower() not in IMAGE_EXTS:
        raise ValueError("El archivo seleccionado no es una imagen compatible.")
    target = destination / f"{prefix}_{uuid.uuid4().hex}{src.suffix.lower()}"
    shutil.copy2(src, target)
    return str(target.relative_to(BASE))


def safe_remove_image(relative_path):
    if not relative_path:
        return
    try:
        p = (BASE / relative_path).resolve()
        # Solo borramos archivos dentro de BASE.
        if BASE.resolve() in p.parents and p.exists() and p.is_file():
            p.unlink()
    except Exception:
        pass


class App(tk.Tk):
    BG = "#f3f5f8"
    CARD = "#ffffff"
    DARK = "#20242a"
    MUTED = "#667085"
    GREEN = "#16a36a"
    ACCENT = "#e9eef3"

    def __init__(self):
        super().__init__()
        self.title("Registro de Ventas")
        self.geometry("1280x820")
        self.minsize(1050, 680)
        self.configure(bg=self.BG)
        self.attributes("-fullscreen", True)
        # Reafirma el modo pantalla completa después de que Windows haya creado la ventana.
        self.after(120, lambda: self.attributes("-fullscreen", True))
        self.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.bind("<Escape>", lambda _e: self.toggle_fullscreen())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.config_data = load_config()
        self.cart = {}  # product_id -> [name, price, quantity]
        self.received = 0
        self.discount_enabled = False
        self.final_total = 0
        self.category = "Todos"
        self.image_cache = {}
        self.money_paths = {int(k): v for k, v in self.config_data.get("dinero", {}).items() if str(k).isdigit()}
        self.sidebar_open = False
        self.sidebar_animating = False
        self.current_view = "sale"

        database().close()
        self.build_header()
        self.body = tk.Frame(self, bg=self.BG)
        self.body.pack(fill="both", expand=True, padx=14, pady=14)
        self.show_sale()

    # --------------------------- UI base ------------------------------------
    def toggle_fullscreen(self):
        current = bool(self.attributes("-fullscreen"))
        self.attributes("-fullscreen", not current)

    def build_header(self):
        header = tk.Frame(self, bg=self.DARK, height=68)
        header.pack(fill="x")
        header.pack_propagate(False)
        self.menu_button = tk.Button(
            header, text="☰", command=self.toggle_sidebar,
            bg=self.DARK, fg="white", activebackground=self.DARK,
            activeforeground="white", relief="flat", bd=0,
            font=("Segoe UI", 22, "bold"), cursor="hand2"
        )
        self.menu_button.pack(side="left", padx=(16, 8))
        self.business_label = tk.Label(
            header, text=self.config_data.get("negocio", "MI NEGOCIO"),
            bg=self.DARK, fg="white", font=("Segoe UI", 17, "bold")
        )
        self.business_label.pack(side="left")
        tk.Button(
            header, text="⚙", command=self.show_settings,
            bg="#30343a", fg="white", activebackground="#444951",
            relief="flat", bd=0, font=("Segoe UI", 14, "bold"), cursor="hand2"
        ).pack(side="right", padx=16, pady=13, ipadx=8, ipady=4)

    def clear_body(self):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.image_cache.clear()

    def make_button(self, parent, text, command, **kwargs):
        opts = dict(relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 10, "bold"))
        opts.update(kwargs)
        return tk.Button(parent, text=text, command=command, **opts)

    # --------------------------- Sidebar -----------------------------------
    def toggle_sidebar(self):
        if self.sidebar_animating:
            return
        if getattr(self, "sidebar", None) and self.sidebar.winfo_exists():
            self.close_sidebar()
        else:
            self.open_sidebar()

    def open_sidebar(self):
        self.sidebar_open = True
        self.sidebar_animating = True
        self.sidebar = tk.Frame(self, bg="white", highlightthickness=1, highlightbackground="#d8dce2")
        self.sidebar.place(x=-285, y=68, width=285, relheight=1.0)
        tk.Label(self.sidebar, text=self.config_data.get("negocio", "MI NEGOCIO"), bg="white",
                 fg="#17191d", font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=20, pady=(22, 18))
        items = [
            ("🛒  Nueva venta", self.show_sale),
            ("📊  Ventas de hoy", lambda: self.show_history("Hoy")),
            ("📅  Ventas de esta semana", lambda: self.show_history("Semana")),
            ("📆  Ventas de este mes", lambda: self.show_history("Mes")),
            ("📦  Productos y categorías", self.show_manager),
            ("👥  Clientes / Fiados", self.show_clients),
            ("⚙  Configuración", self.show_settings),
        ]
        for text, command in items:
            self.make_button(self.sidebar, text, command=self.sidebar_action(command), anchor="w",
                             bg="white", activebackground="#eef1f4", fg="#252a31",
                             font=("Segoe UI", 10, "bold")).pack(fill="x", padx=10, pady=2, ipady=10)
        tk.Frame(self.sidebar, bg="#e9ebef", height=1).pack(fill="x", padx=15, pady=12)
        self.make_button(self.sidebar, "Cerrar menú", command=self.close_sidebar,
                         bg="#eef1f4", activebackground="#e2e6ea", fg="#333").pack(fill="x", padx=20, pady=5, ipady=7)
        self.animate_sidebar(-285, 0, 12)

    def sidebar_action(self, command):
        def run():
            self.close_sidebar(callback=command)
        return run

    def close_sidebar(self, callback=None):
        if not getattr(self, "sidebar", None) or not self.sidebar.winfo_exists():
            if callback:
                callback()
            return
        self.sidebar_animating = True
        self.sidebar_open = False
        self.animate_sidebar(0, -285, -12, callback)

    def animate_sidebar(self, current, target, step, callback=None):
        if not self.sidebar or not self.sidebar.winfo_exists():
            self.sidebar_animating = False
            if callback:
                callback()
            return
        next_x = current + step
        reached = next_x >= target if step > 0 else next_x <= target
        if reached:
            next_x = target
        self.sidebar.place(x=next_x, y=68, width=285, relheight=1.0)
        if reached:
            if target < 0:
                self.sidebar.destroy()
                self.sidebar = None
            self.sidebar_animating = False
            if callback:
                callback()
        else:
            self.after(8, lambda: self.animate_sidebar(next_x, target, step, callback))

    # --------------------------- Sale ---------------------------------------
    def show_sale(self):
        self.current_view = "sale"
        self.clear_body()
        self.body.configure(padx=0, pady=0)

        left = tk.Frame(self.body, bg=self.CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = tk.Frame(self.body, bg=self.CARD, width=370)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # Encabezado: todo queda pegado arriba para aprovechar el espacio.
        # Nueva venta a la izquierda y buscador a la derecha, en la misma fila.
        top = tk.Frame(left, bg="white", height=58)
        top.pack(fill="x", padx=14, pady=(2, 2))
        top.pack_propagate(False)
        top.grid_columnconfigure(1, weight=1)
        title_label = tk.Label(top, text="Nueva venta", bg="white", fg="#17191d",
                               font=("Segoe UI", 22, "bold"))
        title_label.grid(row=0, column=0, sticky="w", pady=4)
        search = tk.Frame(top, bg="white")
        search.grid(row=0, column=1, sticky="ew", padx=(28, 0), pady=4)
        search.grid_columnconfigure(0, weight=1)
        self.query = tk.StringVar()
        entry = tk.Entry(search, textvariable=self.query, font=("Segoe UI", 12),
                         relief="solid", bd=1)
        entry.grid(row=0, column=0, sticky="ew", ipady=7)
        entry.bind("<KeyRelease>", lambda _e: self.render_products())
        self.make_button(search, "🔎", self.render_products, bg="#eef1f4", fg="#252a31",
                         activebackground="#e1e5e9", font=("Segoe UI", 11, "bold"),
                         width=3).grid(row=0, column=1, padx=(6, 0), ipady=5)

        self.categories_bar = tk.Frame(left, bg="white")
        self.categories_bar.pack(fill="x", padx=12, pady=(0, 3))
        self.products_area = tk.Frame(left, bg="white")
        self.products_area.pack(fill="both", expand=True, padx=8, pady=(0, 2))

        # Dinero recibido: siempre abajo, fuera del panel derecho.
        money_box = tk.Frame(left, bg="#f8fafb", highlightthickness=1, highlightbackground="#dde2e7")
        money_box.pack(fill="x", padx=12, pady=(2, 7))
        tk.Label(money_box, text="DINERO RECIBIDO", bg="#f8fafb", fg="#252a31",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(5, 1))
        self.cash_buttons_frame = tk.Frame(money_box, bg="#f8fafb")
        self.cash_buttons_frame.pack(fill="x", padx=8, pady=(0, 3))
        custom = tk.Frame(money_box, bg="#f8fafb")
        custom.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(custom, text="Valor recibido", bg="#f8fafb", fg=self.MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.custom_received_var = tk.StringVar(value="0")
        self.custom_received_entry = tk.Entry(custom, textvariable=self.custom_received_var,
                                              font=("Segoe UI", 12, "bold"), justify="right",
                                              relief="solid", bd=1, width=16)
        self.custom_received_entry.pack(side="left", padx=8, ipady=4)
        self.custom_received_entry.bind("<KeyRelease>", self.on_received_typed)
        self.custom_received_entry.bind("<FocusOut>", self.on_received_typed)
        self.custom_received_entry.bind("<FocusIn>", self.on_received_focus)
        self.custom_received_entry.bind("<<Paste>>", self.on_received_paste)

        # Descuento: solo un cuadrado negro para marcar/desmarcar.
        discount_area = tk.Frame(custom, bg="#f8fafb")
        discount_area.pack(side="left", padx=(14, 4))
        self.discount_var = tk.BooleanVar(value=False)
        self.discount_check = tk.Checkbutton(
            discount_area, text="", variable=self.discount_var,
            command=self.toggle_discount, indicatoron=False,
            bg="white", fg="white", activebackground="white",
            activeforeground="#16a34a", selectcolor="white",
            bd=1, relief="solid", highlightthickness=0,
            width=2, height=1, font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        self.discount_check.pack(side="left", ipadx=2, ipady=1)
        tk.Label(discount_area, text="Descuento", bg="#f8fafb", fg="#333",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(6, 0))

        self.final_price_frame = tk.Frame(money_box, bg="#f8fafb")
        self.final_price_label = tk.Label(
            self.final_price_frame, text="Precio final", bg="#f8fafb",
            fg=self.MUTED, font=("Segoe UI", 9, "bold")
        )
        self.final_price_label.pack(side="left")
        self.final_price_var = tk.StringVar(value="0")
        self.final_price_entry = tk.Entry(
            self.final_price_frame, textvariable=self.final_price_var,
            font=("Segoe UI", 12, "bold"), justify="right",
            relief="solid", bd=1, width=16
        )
        self.final_price_entry.pack(side="left", padx=8, ipady=4)
        self.final_price_entry.bind("<KeyRelease>", self.on_final_price_typed)
        self.final_price_entry.bind("<FocusOut>", self.on_final_price_typed)
        # Se mantiene oculto hasta marcar "Descuento".
        self.render_cash_buttons()

        # Panel derecho: encabezado con VENTA ACTUAL y eliminar al lado.
        current_head = tk.Frame(right, bg="white")
        current_head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(current_head, text="VENTA ACTUAL", bg="white", fg="#17191d",
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        self.make_button(current_head, "Eliminar seleccionado", self.remove_selected,
                         bg="#68717a", fg="white", activebackground="#4f575e",
                         font=("Segoe UI", 8, "bold")).pack(side="right", ipady=3, ipadx=5)

        tree_frame = tk.Frame(right, bg="white")
        tree_frame.pack(fill="both", expand=True, padx=9)
        self.cart_tree = ttk.Treeview(tree_frame, columns=("producto", "precio"), show="headings")
        self.cart_tree.heading("producto", text="Producto / Cant.")
        self.cart_tree.heading("precio", text="Precio")
        self.cart_tree.column("producto", width=225, anchor="w")
        self.cart_tree.column("precio", width=105, anchor="e")
        self.cart_tree.pack(fill="both", expand=True)

        self.total_label = tk.Label(right, text="TOTAL  $0", bg="white", fg="#17191d",
                                    font=("Segoe UI", 18, "bold"), anchor="e")
        self.total_label.pack(fill="x", padx=14, pady=(7, 5))

        tk.Label(right, text="DINERO RECIBIDO", bg="white", fg=self.MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(3, 0))
        self.received_label = tk.Label(right, text="$0", bg="white", fg="#17191d",
                                       font=("Segoe UI", 17, "bold"))
        self.received_label.pack(anchor="w", padx=14)
        self.change_label = tk.Label(right, text="CAMBIO  $0", bg="white", fg=self.GREEN,
                                     font=("Segoe UI", 17, "bold"))
        self.change_label.pack(anchor="w", padx=14, pady=(2, 4))
        self.make_button(right, "Borrar dinero recibido", lambda: self.set_received(0),
                         bg="#68717a", fg="white", activebackground="#4f575e", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=0)
        self.make_button(right, "✓  REGISTRAR VENTA", self.save_sale,
                         bg=self.GREEN, fg="white", activebackground="#128657",
                         font=("Segoe UI", 14, "bold")).pack(fill="x", padx=14, pady=(7, 5), ipady=14)
        self.make_button(right, "Cancelar / nueva venta", self.new_sale,
                         bg="#68717a", fg="white", activebackground="#4f575e", font=("Segoe UI", 9, "bold")).pack(fill="x", padx=14, pady=(0, 8), ipady=6)

        self.load_categories()
        self.update_idletasks()
        self.render_products()
        self.refresh_cart()

    def load_categories(self):
        for w in self.categories_bar.winfo_children():
            w.destroy()
        c = database()
        cats = [row[0] for row in c.execute("SELECT nombre FROM categorias ORDER BY nombre COLLATE NOCASE")]
        c.close()
        if self.category != "Todos" and self.category not in cats:
            self.category = "Todos"
        for name in ["Todos"] + cats:
            self.make_button(self.categories_bar, name,
                             lambda n=name: self.choose_category(n),
                             bg="#dfe6eb" if name == self.category else "#f0f2f4",
                             fg="#1f2933", font=("Segoe UI", 9, "bold")).pack(side="left", padx=2, pady=2, ipady=5, ipadx=5)
        self.make_button(self.categories_bar, "＋ Categoría", self.add_category,
                         bg="#fff1d2", fg="#7a5714").pack(side="left", padx=3, pady=2, ipady=5, ipadx=5)

    def choose_category(self, category):
        self.category = category
        self.load_categories()
        self.render_products()

    def fuzzy_score(self, query, name):
        q, n = normalize(query), normalize(name)
        if not q:
            return 1.0
        if q in n:
            return 0.99
        return SequenceMatcher(None, q, n).ratio()

    def search_rows(self, rows, query):
        if not query:
            return rows, []
        exact = [r for r in rows if normalize(query) in normalize(r[1])]
        if exact:
            return exact, []
        ranked = sorted(rows, key=lambda r: self.fuzzy_score(query, r[1]), reverse=True)
        good = [r for r in ranked if self.fuzzy_score(query, r[1]) >= 0.50]
        suggestions = []
        seen = set()
        for r in good[:5]:
            n = r[1]
            if n.casefold() not in seen:
                suggestions.append(n)
                seen.add(n.casefold())
        # Para errores razonables, mostrar las mejores coincidencias.
        return good[:12], suggestions

    def render_products(self):
        if not hasattr(self, "products_area"):
            return
        for w in self.products_area.winfo_children():
            w.destroy()
        c = database()
        rows = c.execute("SELECT id,nombre,categoria,precio,imagen FROM productos ORDER BY nombre COLLATE NOCASE, id").fetchall()
        c.close()
        if self.category != "Todos":
            rows = [r for r in rows if r[2] == self.category]
        query = self.query.get().strip()
        rows, suggestions = self.search_rows(rows, query)
        if not rows:
            msg = f'No encontramos "{query}".' if query else "Aún no hay productos."
            box = tk.Frame(self.products_area, bg="white")
            box.pack(anchor="center", pady=50)
            tk.Label(box, text=msg, bg="white", fg="#343a40", font=("Segoe UI", 14, "bold")).pack(pady=5)
            self.make_button(box, "＋ Agregar producto", self.add_product,
                             bg="#fff1d2", fg="#76500c").pack(pady=12, ipady=7, ipadx=10)
            return
        if query and suggestions and not any(normalize(query) in normalize(r[1]) for r in rows):
            suggestion = suggestions[0]
            tk.Label(self.products_area, text=f"Intentaste buscar '{query}'. ¿Quizás quisiste decir '{suggestion}'?",
                     bg="white", fg="#667085", font=("Segoe UI", 9, "italic")).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 4))
            start_row = 1
        else:
            start_row = 0

        # Tarjetas un poco más grandes, pero se adaptan al ancho disponible.
        available = max(self.products_area.winfo_width(), 820)
        columns = max(3, min(6, available // 145))
        card_w, card_h = 138, 178
        for col in range(columns):
            self.products_area.grid_columnconfigure(col, weight=1, uniform="product")
        for i, (pid, name, category, price, image) in enumerate(rows):
            r, col = start_row + i // columns, i % columns
            card = tk.Frame(self.products_area, bg="#eef2f5", width=card_w, height=card_h,
                            highlightthickness=1, highlightbackground="#dfe4e8", cursor="hand2")
            card.grid(row=r, column=col, padx=7, pady=6, sticky="nsew")
            card.grid_propagate(False)
            photo = self.load_photo(image, 120, 100, f"product-{pid}")
            if photo:
                visual = tk.Label(card, image=photo, bg="#eef2f5")
                visual.image = photo
            else:
                visual = tk.Label(card, text="🖼\nSin imagen", bg="#eef2f5", fg="#8a939d",
                                  font=("Segoe UI", 10))
            visual.pack(pady=(6, 3))
            name_label = tk.Label(card, text=name, bg="#eef2f5", fg="#20252b", font=("Segoe UI", 9, "bold"),
                                  wraplength=128)
            name_label.pack(pady=(0, 1))
            price_label = tk.Label(card, text=money(price), bg="#eef2f5", fg="#17191d",
                                   font=("Segoe UI", 10, "bold"))
            price_label.pack()
            for widget in (card, visual, name_label, price_label):
                widget.bind("<Button-1>", lambda _e, p=pid: self.add_to_cart(p))
                widget.bind("<Button-3>", lambda _e, p=pid: self.product_context_menu(_e, p))

    def load_photo(self, relative, width, height, key):
        if not relative:
            return None
        path = Path(relative) if Path(relative).is_absolute() else BASE / relative
        if not path.exists():
            return None
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.image_cache[key] = photo
            return photo
        except Exception:
            return None

    def product_context_menu(self, event, pid):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Eliminar producto", command=lambda: self.delete_product_from_sale_view(pid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def delete_product_from_sale_view(self, pid):
        c = database()
        row = c.execute("SELECT nombre,imagen FROM productos WHERE id=?", (pid,)).fetchone()
        c.close()
        if not row:
            return
        if not messagebox.askyesno("Confirmar eliminación", f'¿Eliminar el producto "{row[0]}"?', parent=self):
            return
        c = database()
        c.execute("DELETE FROM productos WHERE id=?", (pid,))
        c.commit()
        c.close()
        safe_remove_image(row[1])
        self.cart.pop(pid, None)
        self.render_products()
        self.refresh_cart()

    def add_to_cart(self, pid):
        c = database()
        row = c.execute("SELECT nombre,precio FROM productos WHERE id=?", (pid,)).fetchone()
        c.close()
        if not row:
            return
        if pid in self.cart:
            self.cart[pid][2] += 1
        else:
            self.cart[pid] = [row[0], int(row[1]), 1]
        self.refresh_cart()

    def remove_selected(self):
        selected = self.cart_tree.selection()
        if not selected:
            return
        iid = selected[0]
        try:
            pid = int(iid)
        except ValueError:
            tags = self.cart_tree.item(iid, "tags")
            if not tags:
                return
            pid = int(tags[0])
        self.cart.pop(pid, None)
        self.refresh_cart()

    def refresh_cart(self):
        if not hasattr(self, "cart_tree"):
            return
        for item in self.cart_tree.get_children():
            self.cart_tree.delete(item)
        subtotal = 0
        for pid, (name, price, quantity) in self.cart.items():
            line_total = price * quantity
            subtotal += line_total
            self.cart_tree.insert("", "end", iid=str(pid), values=(f"{name}  ×{quantity}", money(line_total)), tags=(str(pid),))

        total = self.effective_total()
        self.final_total = total
        if self.discount_enabled:
            descuento = subtotal - total
            self.total_label.config(text=f"TOTAL  {money(total)}   (-{money(descuento)})")
        else:
            self.total_label.config(text=f"TOTAL  {money(total)}")
        self.update_payment_display()

    def render_cash_buttons(self):
        for w in self.cash_buttons_frame.winfo_children():
            w.destroy()

        # Cada billete conserva su propio ancho. No usamos columnas con weight=1,
        # porque eso era lo que producía los grandes huecos de la captura.
        for denomination in DENOMINATIONS:
            relative = self.money_paths.get(denomination, "")
            if not relative:
                default = DEFAULT_MONEY / f"{denomination}.png"
                if default.exists():
                    relative = str(default)
            photo = self.load_photo(relative, 120, 62, f"money-{denomination}")
            holder = tk.Frame(self.cash_buttons_frame, bg="#f8fafb", width=124, height=70)
            holder.pack(side="left", padx=2, pady=1)
            holder.pack_propagate(False)
            btn = self.make_button(
                holder,
                money(denomination) if not photo else "",
                lambda value=denomination: self.add_received(value),
                bg="#edf1f4", fg="#252a31", activebackground="#e0e5e9",
                font=("Segoe UI", 8, "bold")
            )
            btn.pack(fill="both", expand=True)
            if photo:
                btn.configure(image=photo, compound="center")
                btn.image = photo

    def add_received(self, amount):
        self.set_received(self.received + amount)

    def set_received(self, amount):
        self.received = max(0, int(amount))
        self.custom_received_var.set(str(self.received))
        self.update_payment_display()

    def on_received_focus(self, _event=None):
        if self.custom_received_entry.get() == "0":
            self.custom_received_entry.selection_range(0, tk.END)

    def on_received_typed(self, _event=None):
        # El campo ya no reformatea con puntos mientras se escribe.
        # Esto evita que Tk mueva el cursor y cambie 175000 por 170050, etc.
        text = self.custom_received_entry.get()
        value = parse_money(text)
        self.received = value
        self.update_payment_display()

    def on_received_paste(self, _event=None):
        self.after_idle(self.on_received_typed)

    def cart_subtotal(self):
        return sum(price * quantity for _, price, quantity in self.cart.values())

    def effective_total(self):
        subtotal = self.cart_subtotal()
        if not self.discount_enabled:
            return subtotal
        final_value = parse_money(self.final_price_var.get()) if hasattr(self, "final_price_var") else subtotal
        if final_value < 0:
            final_value = 0
        if final_value > subtotal:
            final_value = subtotal
        return final_value

    def toggle_discount(self):
        self.discount_enabled = bool(self.discount_var.get())
        # El cuadro queda blanco con borde negro. Al marcarlo aparece una palomita verde.
        self.discount_check.config(
            text="✓" if self.discount_enabled else "",
            fg="#16a34a" if self.discount_enabled else "white",
            activeforeground="#16a34a" if self.discount_enabled else "white",
            bg="white", activebackground="white", selectcolor="white"
        )
        if self.discount_enabled:
            subtotal = self.cart_subtotal()
            self.final_price_var.set(str(subtotal))
            self.final_price_frame.pack(fill="x", padx=10, pady=(0, 6))
            self.final_price_entry.focus_set()
            self.final_price_entry.selection_range(0, tk.END)
        else:
            self.final_price_frame.pack_forget()
            self.final_total = self.cart_subtotal()
        self.refresh_cart()

    def on_final_price_typed(self, _event=None):
        subtotal = self.cart_subtotal()
        value = parse_money(self.final_price_var.get())
        if value > subtotal:
            value = subtotal
            self.final_price_var.set(str(value))
        self.final_total = value
        self.update_payment_display()

    def update_payment_display(self):
        if not hasattr(self, "received_label"):
            return
        total = self.effective_total()
        difference = self.received - total
        self.received_label.config(text=money(self.received))
        if difference >= 0:
            self.change_label.config(text=f"CAMBIO  {money(difference)}", fg=self.GREEN)
        else:
            self.change_label.config(text=f"FALTA  {money(-difference)}", fg="#b42318")

    def save_sale(self):
        if not self.cart:
            messagebox.showwarning("Venta", "Agrega al menos un producto.")
            return
        subtotal = self.cart_subtotal()
        total = self.effective_total()
        descuento = subtotal - total
        if self.received < total:
            messagebox.showwarning("Pago insuficiente", "El dinero recibido no alcanza para cubrir el total.")
            return
        now = datetime.now().replace(microsecond=0)
        c = database()
        cur = c.cursor()
        cur.execute("INSERT INTO ventas(fecha,total,recibido,cambio,descuento) VALUES(?,?,?,?,?)",
                    (now.isoformat(sep=" "), total, self.received, self.received - total, descuento))
        sale_id = cur.lastrowid
        # Guardar siempre el precio original del producto.
        # El descuento se guarda en la venta, no se modifica el precio unitario.
        rows = [
            (sale_id, name, quantity, price)
            for name, price, quantity in self.cart.values()
        ]
        cur.executemany(
            "INSERT INTO detalle(venta_id,nombre,cantidad,precio) VALUES(?,?,?,?)",
            rows
        )
        c.commit()
        c.close()
        descuento_texto = f"\nDescuento: {money(descuento)}" if descuento else ""
        messagebox.showinfo("Venta registrada", f"Venta #{sale_id}\nTotal: {money(total)}{descuento_texto}\nRecibido: {money(self.received)}\nCambio: {money(self.received - total)}")
        self.new_sale()

    def new_sale(self):
        self.cart.clear()
        self.received = 0
        self.discount_enabled = False
        self.final_total = 0
        if hasattr(self, "custom_received_var"):
            self.custom_received_var.set("0")
        if hasattr(self, "discount_var"):
            self.discount_var.set(False)
        if hasattr(self, "final_price_var"):
            self.final_price_var.set("0")
        if hasattr(self, "final_price_frame"):
            self.final_price_frame.pack_forget()
        self.refresh_cart()

    # --------------------------- History -----------------------------------
    def period_start(self, period):
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "Años":
            self._history_years()
            return

        if period == "Hoy":
            return today
        if period == "Semana":
            return today - timedelta(days=today.weekday())
        return today.replace(day=1)

    def period_end(self, period):
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "Hoy":
            return today + timedelta(days=1)
        if period == "Semana":
            return today - timedelta(days=today.weekday()) + timedelta(days=7)
        if today.month == 12:
            return today.replace(year=today.year + 1, month=1, day=1)
        return today.replace(month=today.month + 1, day=1)

    def _history_query(self, start_date, end_date):
        c = database()
        rows = c.execute(
            """SELECT d.venta_id, d.id, v.fecha, d.nombre, d.cantidad,
                      d.precio, v.total, v.descuento
               FROM detalle d
               JOIN ventas v ON v.id = d.venta_id
               WHERE v.fecha >= ? AND v.fecha < ?
               ORDER BY v.fecha ASC, v.id ASC, d.id ASC""",
            (start_date.isoformat(sep=" "), end_date.isoformat(sep=" "))
        ).fetchall()
        c.close()
        return rows

    def _history_sales_total(self, start_date, end_date):
        rows = self._history_query(start_date, end_date)
        seen = set()
        total = 0
        for sale_id, detail_id, fecha, nombre, cantidad, precio, sale_total, discount in rows:
            if sale_id not in seen:
                total += int(round(sale_total or 0))
                seen.add(sale_id)
        return total

    def _history_grouped_sales(self, start_date, end_date):
        rows = self._history_query(start_date, end_date)
        sales = {}
        for sale_id, detail_id, fecha, nombre, cantidad, precio, sale_total, discount in rows:
            if sale_id not in sales:
                sales[sale_id] = {
                    "fecha": fecha,
                    "total": int(round(sale_total or 0)),
                    "descuento": int(round(discount or 0)),
                    "items": []
                }
            sales[sale_id]["items"].append(
                (detail_id, nombre, int(cantidad), int(round(precio)))
            )

        # Reconstruye siempre el precio original y evita errores como 299.997.
        for sale in sales.values():
            items = sale["items"]
            discount = sale["descuento"]
            original_total = sale["total"] + discount
            previous_original = 0
            rebuilt = []
            for index, (detail_id, name, quantity, stored_price) in enumerate(items):
                if index < len(items) - 1 or not discount:
                    unit_price = stored_price
                    line_original = unit_price * quantity
                else:
                    line_original = max(0, original_total - previous_original)
                    unit_price = line_original // quantity if quantity else 0
                line_discount = discount if index == len(items) - 1 else 0
                line_total = line_original - line_discount
                rebuilt.append({
                    "detail_id": detail_id,
                    "nombre": name,
                    "cantidad": quantity,
                    "precio": unit_price,
                    "descuento": line_discount,
                    "total": line_total
                })
                previous_original += line_original
            sale["items_rebuilt"] = rebuilt
        return sales

    def _history_products_window(self, title, start_date, end_date):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("980x560")
        win.minsize(820, 460)

        tk.Label(
            win, text=title, font=("Segoe UI", 15, "bold"),
            anchor="w"
        ).pack(fill="x", padx=14, pady=(12, 6))

        frame = tk.Frame(win, bg="white")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(
            frame,
            columns=("fecha", "cantidad", "producto", "precio", "descuento", "total"),
            show="headings"
        )
        for col, text, width in [
            ("fecha", "Fecha", 130),
            ("cantidad", "Cantidad", 80),
            ("producto", "Producto", 300),
            ("precio", "Precio", 125),
            ("descuento", "Descuento", 130),
            ("total", "Total", 145)
        ]:
            tree.heading(col, text=text)
            tree.column(
                col, width=width,
                anchor="center" if col != "producto" else "w"
            )
        tree.pack(fill="both", expand=True)

        sales = self._history_grouped_sales(start_date, end_date)
        for sale in sales.values():
            try:
                date_display = datetime.fromisoformat(sale["fecha"]).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                date_display = str(sale["fecha"])
            for item in sale["items_rebuilt"]:
                tree.insert("", "end", values=(
                    date_display,
                    item["cantidad"],
                    item["nombre"],
                    money(item["precio"]),
                    money(item["descuento"]) if item["descuento"] else "",
                    money(item["total"])
                ))

        total = self._history_sales_total(start_date, end_date)
        tk.Label(
            win, text=f"TOTAL: {money(total)}",
            font=("Segoe UI", 12, "bold"), anchor="e"
        ).pack(fill="x", padx=14, pady=(0, 12))

    def _history_week_products_menu(self, tree, ranges):
        menu = tk.Menu(self, tearoff=0)

        def show_products():
            item = tree.focus()
            if item in ranges:
                ds, de, label = ranges[item]
                self._history_products_window(
                    f"Productos vendidos - {label}", ds, de
                )

        menu.add_command(label="Ver productos vendidos", command=show_products)

        def popup(event):
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
                tree.focus(iid)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

    def _history_week(self, week_start):
        week_end = week_start + timedelta(days=7)
        weekdays = [
            "Lunes", "Martes", "Miércoles", "Jueves",
            "Viernes", "Sábado", "Domingo"
        ]

        tk.Label(
            self.body, text="VENTAS DE ESTA SEMANA",
            bg=self.BG, fg="#17191d",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            self.body,
            text=f"{week_start.strftime('%d/%m/%Y')} - {(week_end - timedelta(days=1)).strftime('%d/%m/%Y')}  •  Clic derecho en un día para ver productos",
            bg=self.BG, fg=self.MUTED,
            font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 8))

        frame = tk.Frame(self.body, bg="white")
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            frame, columns=("dia", "total"), show="headings"
        )
        tree.heading("dia", text="Día")
        tree.heading("total", text="Total")
        tree.column("dia", width=300, anchor="w")
        tree.column("total", width=220, anchor="e")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        ranges = {}
        week_total = 0
        for i, day_name in enumerate(weekdays):
            ds = week_start + timedelta(days=i)
            de = ds + timedelta(days=1)
            total = self._history_sales_total(ds, de)
            week_total += total
            iid = tree.insert("", "end", values=(day_name, money(total)))
            ranges[iid] = (ds, de, f"{day_name} {ds.strftime('%d/%m/%Y')}")

        self._history_week_products_menu(tree, ranges)

        tk.Label(
            self.body, text=f"TOTAL DE LA SEMANA: {money(week_total)}",
            bg=self.BG, fg="#17191d",
            font=("Segoe UI", 13, "bold")
        ).pack(anchor="e", pady=(8, 0))

    def _history_month_weeks(self, month_start, month_end, month_name):
        win = tk.Toplevel(self)
        win.title(f"Semanas de {month_name}")
        win.geometry("760x520")
        win.minsize(650, 440)

        tk.Label(
            win, text=f"SEMANAS DE {month_name.upper()}",
            font=("Segoe UI", 15, "bold"), anchor="w"
        ).pack(fill="x", padx=14, pady=(12, 4))

        tk.Label(
            win,
            text="Clic derecho sobre una semana para ver los productos vendidos.",
            fg="#68717a", font=("Segoe UI", 9), anchor="w"
        ).pack(fill="x", padx=14, pady=(0, 8))

        frame = tk.Frame(win, bg="white")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(
            frame, columns=("semana", "periodo", "total"), show="headings"
        )
        tree.heading("semana", text="Semana")
        tree.heading("periodo", text="Periodo")
        tree.heading("total", text="Total")
        tree.column("semana", width=120, anchor="center")
        tree.column("periodo", width=250, anchor="center")
        tree.column("total", width=170, anchor="e")
        tree.pack(fill="both", expand=True)

        ranges = {}
        cursor = month_start - timedelta(days=month_start.weekday())
        week_number = 1
        month_total = 0

        while cursor < month_end:
            full_start = cursor
            full_end = cursor + timedelta(days=7)

            # La semana siempre es lunes-domingo, pero dentro del mes
            # solo se contabiliza lo que pertenece a ese mes.
            rs = max(full_start, month_start)
            re_ = min(full_end, month_end)

            total = self._history_sales_total(rs, re_)
            month_total += total

            period_label = (
                f"{rs.strftime('%d/%m/%Y')} - "
                f"{(re_ - timedelta(days=1)).strftime('%d/%m/%Y')}"
            )
            iid = tree.insert(
                "", "end",
                values=(f"Semana {week_number}", period_label, money(total))
            )
            ranges[iid] = (
                rs, re_,
                f"{month_name} — Semana {week_number} ({period_label})"
            )

            cursor = full_end
            week_number += 1

        menu = tk.Menu(win, tearoff=0)

        def show_products():
            item = tree.focus()
            if item in ranges:
                rs, re_, label = ranges[item]
                self._history_products_window(label, rs, re_)

        menu.add_command(label="Ver productos vendidos", command=show_products)

        def popup(event):
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
                tree.focus(iid)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

        tk.Label(
            win, text=f"TOTAL DE {month_name.upper()}: {money(month_total)}",
            font=("Segoe UI", 12, "bold"), anchor="e"
        ).pack(fill="x", padx=14, pady=(0, 12))

    def _history_months(self, year):
        months = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]

        tk.Label(
            self.body, text=f"VENTAS DE {year}",
            bg=self.BG, fg="#17191d",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            self.body,
            text="Solo se muestran los totales. Clic derecho en un mes para ver sus semanas.",
            bg=self.BG, fg=self.MUTED,
            font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 8))

        frame = tk.Frame(self.body, bg="white")
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            frame, columns=("mes", "total"), show="headings"
        )
        tree.heading("mes", text="Mes")
        tree.heading("total", text="Total")
        tree.column("mes", width=300, anchor="w")
        tree.column("total", width=220, anchor="e")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        ranges = {}
        year_total = 0

        for month in range(1, 13):
            ms = datetime(year, month, 1)
            me = (
                datetime(year + 1, 1, 1)
                if month == 12
                else datetime(year, month + 1, 1)
            )
            total = self._history_sales_total(ms, me)
            year_total += total
            iid = tree.insert("", "end", values=(months[month - 1], money(total)))
            ranges[iid] = (ms, me, months[month - 1])

        menu = tk.Menu(self, tearoff=0)

        def show_weeks():
            item = tree.focus()
            if item in ranges:
                ms, me, name = ranges[item]
                self._history_month_weeks(ms, me, name)

        menu.add_command(label="Ver semanas", command=show_weeks)

        def popup(event):
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
                tree.focus(iid)
                menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", popup)

        tk.Label(
            self.body, text=f"TOTAL DEL AÑO: {money(year_total)}",
            bg=self.BG, fg="#17191d",
            font=("Segoe UI", 13, "bold")
        ).pack(anchor="e", pady=(8, 0))


    def _history_years(self):
        for w in self.body.winfo_children(): w.destroy()
        c = database()
        rows = c.execute("SELECT fecha, total FROM ventas ORDER BY fecha ASC").fetchall()
        c.close()
        totals = {}
        for fecha, total in rows:
            try:
                y = datetime.fromisoformat(fecha).year
            except Exception:
                try: y = datetime.strptime(str(fecha)[:10], "%Y-%m-%d").year
                except Exception: continue
            totals[y] = totals.get(y, 0) + int(round(total or 0))

        tk.Label(self.body, text="VENTAS POR AÑO", bg=self.BG, fg="#17191d",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0,4))
        tk.Label(self.body, text="Clic derecho sobre un año para ver sus meses.",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI",9)).pack(anchor="w", pady=(0,8))
        frame = tk.Frame(self.body, bg="white"); frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("anio","total"), show="headings")
        tree.heading("anio", text="Año"); tree.heading("total", text="Total")
        tree.column("anio", width=300, anchor="w"); tree.column("total", width=220, anchor="e")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        years = {}
        for y in sorted(totals, reverse=True):
            iid = tree.insert("", "end", values=(y, money(totals[y])))
            years[iid] = y

        menu = tk.Menu(self, tearoff=0)
        def months():
            iid = tree.focus()
            if iid in years: self._history_year_months(years[iid])
        menu.add_command(label="Ver meses", command=months)
        def popup(e):
            iid = tree.identify_row(e.y)
            if iid:
                tree.selection_set(iid); tree.focus(iid)
                menu.tk_popup(e.x_root, e.y_root)
        tree.bind("<Button-3>", popup)
        tk.Label(self.body, text=f"TOTAL GENERAL: {money(sum(totals.values()))}",
                 bg=self.BG, fg="#17191d", font=("Segoe UI",13,"bold")).pack(anchor="e", pady=(8,0))

    def _history_year_months(self, year):
        names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto",
                 "Septiembre","Octubre","Noviembre","Diciembre"]
        win = tk.Toplevel(self); win.title(f"Meses de {year}"); win.geometry("760x520")
        tk.Label(win, text=f"MESES DE {year}", font=("Segoe UI",15,"bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(12,4))
        tk.Label(win, text="Clic derecho sobre un mes para ver sus semanas.",
                 fg="#68717a", font=("Segoe UI",9), anchor="w").pack(fill="x", padx=14, pady=(0,8))
        frame = tk.Frame(win, bg="white"); frame.pack(fill="both", expand=True, padx=10, pady=10)
        tree = ttk.Treeview(frame, columns=("mes","total"), show="headings")
        tree.heading("mes", text="Mes"); tree.heading("total", text="Total")
        tree.column("mes", width=300, anchor="w"); tree.column("total", width=220, anchor="e")
        tree.pack(fill="both", expand=True)
        ranges = {}; year_total = 0
        for m in range(1,13):
            a = datetime(year,m,1)
            b = datetime(year+1,1,1) if m==12 else datetime(year,m+1,1)
            total = self._history_sales_total(a,b); year_total += total
            iid = tree.insert("", "end", values=(names[m-1], money(total)))
            ranges[iid] = (a,b,names[m-1])
        menu = tk.Menu(win, tearoff=0)
        def weeks():
            iid=tree.focus()
            if iid in ranges:
                a,b,n=ranges[iid]; self._history_month_weeks(a,b,n)
        menu.add_command(label="Ver semanas", command=weeks)
        def popup(e):
            iid=tree.identify_row(e.y)
            if iid:
                tree.selection_set(iid); tree.focus(iid); menu.tk_popup(e.x_root,e.y_root)
        tree.bind("<Button-3>", popup)
        tk.Label(win, text=f"TOTAL DE {year}: {money(year_total)}",
                 font=("Segoe UI",12,"bold"), anchor="e").pack(fill="x", padx=14, pady=(0,12))

    def show_history(self, period="Hoy"):
        self.current_view = "history"
        self.clear_body()

        now = datetime.now()
        weekdays = [
            "Lunes", "Martes", "Miércoles", "Jueves",
            "Viernes", "Sábado", "Domingo"
        ]

        tabs = tk.Frame(self.body, bg=self.BG)
        tabs.pack(fill="x", pady=(0, 8))
        for p in ("Hoy", "Semana", "Mes", "Años"):
            self.make_button(
                tabs, p, lambda x=p: self.show_history(x),
                bg="#dfe6eb" if p == period else "#ffffff",
                fg="#252a31"
            ).pack(side="left", padx=3, ipady=5, ipadx=8)

        if period == "Hoy":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)

            head = tk.Frame(self.body, bg="white")
            head.pack(fill="x", pady=(0, 10))
            tk.Label(
                head,
                text=f"Ventas de hoy — {weekdays[now.weekday()]}",
                bg="white", fg="#17191d",
                font=("Segoe UI", 21, "bold")
            ).pack(anchor="w", padx=18, pady=(15, 3))

            total = self._history_sales_total(start, end)
            sales = self._history_grouped_sales(start, end)
            tk.Label(
                head,
                text=f"{len(sales)} ventas   •   Total cobrado: {money(total)}",
                bg="white", fg=self.MUTED,
                font=("Segoe UI", 11, "bold")
            ).pack(anchor="w", padx=18, pady=(0, 15))

            frame = tk.Frame(self.body, bg="white")
            frame.pack(fill="both", expand=True)

            tree = ttk.Treeview(
                frame,
                columns=("fecha", "cantidad", "producto", "precio", "descuento", "total"),
                show="headings"
            )
            for col, text, width in [
                ("fecha", "Fecha", 125),
                ("cantidad", "Cantidad", 80),
                ("producto", "Producto", 270),
                ("precio", "Precio", 125),
                ("descuento", "Descuento", 125),
                ("total", "Total", 145)
            ]:
                tree.heading(col, text=text)
                tree.column(
                    col, width=width,
                    anchor="center" if col != "producto" else "w"
                )
            tree.pack(fill="both", expand=True, padx=10, pady=10)

            for sale in sales.values():
                try:
                    date_display = datetime.fromisoformat(
                        sale["fecha"]
                    ).strftime("%d/%m/%Y %H:%M")
                except ValueError:
                    date_display = str(sale["fecha"])

                for item in sale["items_rebuilt"]:
                    tree.insert("", "end", values=(
                        date_display,
                        item["cantidad"],
                        item["nombre"],
                        money(item["precio"]),
                        money(item["descuento"]) if item["descuento"] else "",
                        money(item["total"])
                    ))

            # Los abonos también aparecen en la sección VENTAS, claramente
            # identificados como "ABONO — Nombre del cliente".
            c = database()
            abonos = c.execute(
                """SELECT mc.fecha, mc.monto, cl.nombre, mc.concepto
                   FROM movimientos_clientes mc
                   JOIN clientes cl ON cl.id = mc.cliente_id
                   WHERE mc.tipo = 'ABONO' AND mc.fecha >= ? AND mc.fecha < ?
                   ORDER BY mc.fecha ASC, mc.id ASC""",
                (start.isoformat(sep=" "), end.isoformat(sep=" "))
            ).fetchall()
            c.close()
            for fecha, monto, nombre, concepto in abonos:
                try:
                    date_display = datetime.fromisoformat(fecha).strftime("%d/%m/%Y %H:%M")
                except ValueError:
                    date_display = str(fecha)
                detalle_abono = f"ABONO — {nombre}"
                if concepto:
                    detalle_abono += f" ({concepto})"
                tree.insert("", "end", values=(
                    date_display, "", detalle_abono, "", "", money(monto)
                ))

            tk.Label(
                self.body, text=f"TOTAL DE HOY: {money(total)}",
                bg=self.BG, fg="#17191d",
                font=("Segoe UI", 13, "bold")
            ).pack(anchor="e", pady=(8, 0))
            return

        if period == "Semana":
            week_start = (
                now - timedelta(days=now.weekday())
            ).replace(hour=0, minute=0, second=0, microsecond=0)
            self._history_week(week_start)
            return

        self._history_months(now.year)

    def show_sale_detail(self, tree):
        selected = tree.selection()
        if not selected:
            return
        sale_id = int(tree.item(selected[0], "tags")[0])
        c = database()
        rows = c.execute("SELECT nombre,cantidad,precio FROM detalle WHERE venta_id=?", (sale_id,)).fetchall()
        c.close()
        messagebox.showinfo("Detalle de venta", "\n".join(f"{name} ×{qty} — {money(price)}" for name, qty, price in rows) or "Sin detalle.")

    # --------------------------- Product/category manager ------------------
    def show_manager(self):
        self.current_view = "manager"
        self.clear_body()
        tk.Label(self.body, text="Productos y categorías", bg=self.BG, fg="#17191d",
                 font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(5, 2))
        tk.Label(self.body, text="Aquí puedes agregar, eliminar y administrar tus productos y categorías.",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))
        actions = tk.Frame(self.body, bg=self.BG)
        actions.pack(fill="x", pady=5)
        self.make_button(actions, "＋ Agregar producto", self.add_product, bg=self.GREEN, fg="white").pack(side="left", ipady=7, ipadx=8)
        self.make_button(actions, "＋ Agregar categoría", self.add_category, bg="#fff1d2", fg="#76500c").pack(side="left", padx=7, ipady=7, ipadx=8)
        self.make_button(actions, "Eliminar producto", self.delete_product, bg="#ffe7e5", fg="#a5261f").pack(side="right", ipady=7, ipadx=8)
        self.make_button(actions, "Eliminar categoría", self.delete_category, bg="#ffe7e5", fg="#a5261f").pack(side="right", padx=7, ipady=7, ipadx=8)

        frame = tk.Frame(self.body, bg="white")
        frame.pack(fill="both", expand=True, pady=8)
        self.manager_tree = ttk.Treeview(frame, columns=("id", "name", "cat", "price", "img"), show="headings")
        for col, text, width in [("id", "ID", 60), ("name", "Producto", 300), ("cat", "Categoría", 190), ("price", "Precio", 150), ("img", "Imagen", 100)]:
            self.manager_tree.heading(col, text=text)
            self.manager_tree.column(col, width=width, anchor="center" if col != "name" else "w")
        self.manager_tree.pack(fill="both", expand=True, padx=10, pady=10)
        c = database()
        rows = c.execute("SELECT id,nombre,categoria,precio,imagen FROM productos ORDER BY nombre COLLATE NOCASE,id").fetchall()
        c.close()
        for pid, name, cat, price, image in rows:
            self.manager_tree.insert("", "end", values=(pid, name, cat, money(price), "✓" if image else "—"), tags=(str(pid),))

    def add_product(self):
        w = tk.Toplevel(self)
        w.title("Agregar producto")
        w.geometry("720x790")
        w.resizable(True, True)
        w.transient(self)
        w.grab_set()
        w.configure(bg="white")
        tk.Label(w, text="Agregar producto", bg="white", fg="#17191d", font=("Segoe UI", 19, "bold")).pack(pady=(20, 14))
        form = tk.Frame(w, bg="white")
        form.pack(fill="x", padx=30)
        tk.Label(form, text="Nombre", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        name_entry = tk.Entry(form, font=("Segoe UI", 12), relief="solid", bd=1)
        name_entry.pack(fill="x", pady=(3, 12), ipady=6)
        tk.Label(form, text="Precio", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        price_var = tk.StringVar(value="0")
        price_entry = tk.Entry(form, textvariable=price_var, font=("Segoe UI", 12), relief="solid", bd=1, justify="right")
        price_entry.pack(fill="x", pady=(3, 12), ipady=6)
        # El precio se deja escribir/pegar sin insertar puntos automáticamente.
        # Al guardar se convierte a número entero.
        c = database()
        categories = [r[0] for r in c.execute("SELECT nombre FROM categorias ORDER BY nombre COLLATE NOCASE")]
        c.close()
        tk.Label(form, text="Categoría", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        category_var = tk.StringVar(value=categories[0] if categories else "")
        combo = ttk.Combobox(form, textvariable=category_var, values=categories, state="readonly" if categories else "disabled")
        combo.pack(fill="x", pady=(3, 12), ipady=4)
        image_holder = {"path": "", "relative": ""}
        preview_frame = tk.Frame(w, bg="#f0f2f4", width=620, height=300,
                                 highlightthickness=1, highlightbackground="#dfe3e8")
        preview_frame.pack(fill="both", expand=True, padx=30, pady=8)
        preview_frame.pack_propagate(False)
        preview = tk.Label(preview_frame, text="Sin imagen seleccionada", bg="#f0f2f4", fg="#7a828a",
                           font=("Segoe UI", 10), anchor="center", justify="center")
        preview.pack(fill="both", expand=True)

        def choose_image():
            path = filedialog.askopenfilename(parent=w, filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
            if not path:
                return
            image_holder["path"] = path
            try:
                im = Image.open(path).convert("RGB")
                im.thumbnail((590, 285), Image.Resampling.LANCZOS)
                ph = ImageTk.PhotoImage(im)
                preview.configure(image=ph, text="")
                preview.image = ph
            except Exception:
                messagebox.showerror("Imagen", "No se pudo abrir esa imagen.", parent=w)

        self.make_button(w, "🖼 Seleccionar imagen", choose_image, bg="#e9edf1", fg="#252a31").pack(pady=6, ipady=7, ipadx=8)

        def save():
            name = name_entry.get().strip()
            price = parse_money(price_var.get())
            category = category_var.get().strip()
            if not name:
                messagebox.showerror("Producto", "Escribe el nombre del producto.", parent=w)
                return
            if price < 0:
                messagebox.showerror("Producto", "El precio no puede ser negativo.", parent=w)
                return
            if not category:
                messagebox.showwarning("Producto", "Primero agrega una categoría.", parent=w)
                return
            try:
                relative = copy_image(image_holder["path"], PRODUCTS, "producto") if image_holder["path"] else ""
                c = database()
                # No UNIQUE en nombre: los nombres repetidos están permitidos.
                c.execute("INSERT INTO productos(nombre,categoria,precio,imagen) VALUES(?,?,?,?)", (name, category, price, relative))
                c.commit()
                c.close()
                w.destroy()
                self.refresh_current_view()
            except Exception as exc:
                messagebox.showerror("Producto", f"No se pudo guardar el producto.\n{exc}", parent=w)

        self.make_button(w, "GUARDAR PRODUCTO", save, bg=self.GREEN, fg="white",
                         font=("Segoe UI", 11, "bold")).pack(fill="x", padx=30, pady=18, ipady=9)
        name_entry.focus_set()

    def add_category(self):
        w = tk.Toplevel(self)
        w.title("Nueva categoría")
        w.geometry("430x220")
        w.transient(self)
        w.grab_set()
        w.configure(bg="white")
        tk.Label(w, text="Nueva categoría", bg="white", font=("Segoe UI", 18, "bold")).pack(pady=20)
        entry = tk.Entry(w, font=("Segoe UI", 12), relief="solid", bd=1)
        entry.pack(fill="x", padx=30, ipady=7)
        def save():
            name = entry.get().strip()
            if not name:
                return
            try:
                c = database()
                c.execute("INSERT INTO categorias(nombre) VALUES(?)", (name,))
                c.commit()
                c.close()
                w.destroy()
                self.refresh_current_view()
            except sqlite3.IntegrityError:
                messagebox.showwarning("Categoría", "Esa categoría ya existe.", parent=w)
        self.make_button(w, "GUARDAR", save, bg=self.GREEN, fg="white").pack(pady=18, ipady=7, ipadx=15)
        entry.focus_set()

    def delete_product(self):
        if not hasattr(self, "manager_tree"):
            return
        selected = self.manager_tree.selection()
        if not selected:
            messagebox.showwarning("Eliminar producto", "Selecciona un producto primero.")
            return
        pid = int(self.manager_tree.item(selected[0], "tags")[0])
        c = database()
        row = c.execute("SELECT nombre,imagen FROM productos WHERE id=?", (pid,)).fetchone()
        c.close()
        if not row:
            return
        if not messagebox.askyesno("Confirmar eliminación", f'¿Eliminar el producto "{row[0]}"?', parent=self):
            return
        c = database()
        c.execute("DELETE FROM productos WHERE id=?", (pid,))
        c.commit()
        c.close()
        safe_remove_image(row[1])
        self.cart.pop(pid, None)
        self.show_manager()

    def delete_category(self):
        # Un selector sencillo dentro de la misma ventana de gestión.
        c = database()
        cats = [r[0] for r in c.execute("SELECT nombre FROM categorias ORDER BY nombre COLLATE NOCASE")]
        c.close()
        if not cats:
            messagebox.showinfo("Categorías", "No hay categorías para eliminar.")
            return
        w = tk.Toplevel(self)
        w.title("Eliminar categoría")
        w.geometry("430x260")
        w.transient(self)
        w.grab_set()
        w.configure(bg="white")
        tk.Label(w, text="Eliminar categoría", bg="white", font=("Segoe UI", 18, "bold")).pack(pady=18)
        var = tk.StringVar(value=cats[0])
        ttk.Combobox(w, textvariable=var, values=cats, state="readonly").pack(fill="x", padx=30, ipady=5)
        tk.Label(w, text="No se puede eliminar una categoría que todavía tenga productos.", bg="white", fg="#667085",
                 wraplength=350, font=("Segoe UI", 9)).pack(pady=12)
        def delete():
            category = var.get()
            c = database()
            count = c.execute("SELECT COUNT(*) FROM productos WHERE categoria=?", (category,)).fetchone()[0]
            if count:
                c.close()
                messagebox.showwarning("Categoría", f"No se puede eliminar '{category}' porque tiene {count} producto(s).", parent=w)
                return
            if not messagebox.askyesno("Confirmar eliminación", f"¿Eliminar la categoría '{category}'?", parent=w):
                c.close()
                return
            c.execute("DELETE FROM categorias WHERE nombre=?", (category,))
            c.commit()
            c.close()
            w.destroy()
            self.refresh_current_view()
        self.make_button(w, "ELIMINAR", delete, bg="#d92d20", fg="white").pack(pady=8, ipady=7, ipadx=15)

    # --------------------------- Clients / Fiados -------------------------
    def client_balance(self, client_id, c=None):
        own = c is None
        if own:
            c = database()
        balance = c.execute("""SELECT COALESCE(SUM(CASE WHEN tipo='FIADO' THEN monto ELSE -monto END),0)
                              FROM movimientos_clientes WHERE cliente_id=?""", (client_id,)).fetchone()[0]
        if own:
            c.close()
        return int(balance or 0)

    def show_clients(self):
        self.current_view = "clients"
        self.clear_body()
        self.body.configure(padx=14, pady=14)

        top = tk.Frame(self.body, bg=self.BG)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Clientes / Fiados", bg=self.BG, fg="#17191d",
                 font=("Segoe UI", 22, "bold")).pack(side="left")
        self.make_button(top, "＋ Nuevo cliente", self.add_client,
                         bg=self.GREEN, fg="white", activebackground="#128657",
                         font=("Segoe UI", 10, "bold")).pack(side="right", ipady=7, ipadx=10)

        info = tk.Frame(self.body, bg="#fff8e7", highlightthickness=1, highlightbackground="#f1d28b")
        info.pack(fill="x", pady=(0, 10))
        tk.Label(info, text="Aquí puedes llevar las cuentas de las personas a las que les fías.",
                 bg="#fff8e7", fg="#6b5315", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(info, text="Registra cada fiado y cada abono para saber exactamente cuánto debe cada cliente.",
                 bg="#fff8e7", fg="#7b6a3c", font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(0, 8))

        search_frame = tk.Frame(self.body, bg="white")
        search_frame.pack(fill="x", pady=(0, 8))
        tk.Label(search_frame, text="Buscar cliente", bg="white", fg=self.MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 6), pady=9)
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, font=("Segoe UI", 11), relief="solid", bd=1)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=5)

        table_card = tk.Frame(self.body, bg="white")
        table_card.pack(fill="both", expand=True)
        columns = ("nombre", "telefono", "debe", "estado")
        tree = ttk.Treeview(table_card, columns=columns, show="headings", selectmode="browse")
        tree.heading("nombre", text="Cliente")
        tree.heading("telefono", text="Teléfono")
        tree.heading("debe", text="Debe")
        tree.heading("estado", text="Estado")
        tree.column("nombre", width=300, anchor="w")
        tree.column("telefono", width=180, anchor="w")
        tree.column("debe", width=180, anchor="e")
        tree.column("estado", width=150, anchor="center")
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        self.clients_tree = tree

        actions = tk.Frame(self.body, bg=self.BG)
        actions.pack(fill="x", pady=(8, 0))
        self.make_button(actions, "＋ Registrar fiado", lambda: self.client_movement("FIADO"),
                         bg="#20242a", fg="white", activebackground="#111111").pack(side="left", padx=(0, 6), ipady=7, ipadx=8)
        self.make_button(actions, "💰 Registrar abono", lambda: self.client_movement("ABONO"),
                         bg=self.GREEN, fg="white", activebackground="#128657").pack(side="left", padx=6, ipady=7, ipadx=8)
        self.make_button(actions, "📋 Ver movimientos", self.show_client_movements,
                         bg="#e9edf1", fg="#252a31").pack(side="left", padx=6, ipady=7, ipadx=8)
        self.make_button(actions, "✏ Editar", self.edit_client,
                         bg="#e9edf1", fg="#252a31").pack(side="right", padx=6, ipady=7, ipadx=8)
        self.make_button(actions, "🗑 Eliminar", self.delete_client,
                         bg="#d92d20", fg="white", activebackground="#b42318").pack(side="right", ipady=7, ipadx=8)

        def refresh(*_):
            query = normalize(search_var.get())
            for item in tree.get_children():
                tree.delete(item)
            c = database()
            rows = c.execute("SELECT id,nombre,telefono FROM clientes ORDER BY nombre COLLATE NOCASE").fetchall()
            for cid, name, phone in rows:
                if query and query not in normalize(name) and query not in normalize(phone):
                    continue
                balance = self.client_balance(cid, c)
                state = "Pendiente" if balance > 0 else "Al día"
                tree.insert("", "end", iid=str(cid), values=(name, phone or "—", money(balance), state))
            c.close()
        search_var.trace_add("write", refresh)
        refresh()

    def selected_client_id(self):
        if not hasattr(self, "clients_tree"):
            return None
        selected = self.clients_tree.selection()
        if not selected:
            messagebox.showwarning("Cliente", "Selecciona un cliente primero.", parent=self)
            return None
        return int(selected[0])

    def add_client(self):
        self.client_form()

    def edit_client(self):
        cid = self.selected_client_id()
        if not cid:
            return
        c = database()
        row = c.execute("SELECT nombre,telefono,notas FROM clientes WHERE id=?", (cid,)).fetchone()
        c.close()
        if row:
            self.client_form(cid, row)

    def client_form(self, cid=None, row=None):
        # Al crear un cliente, el pedido se selecciona en esta misma ventana.
        # Así no hay que crear primero el cliente y luego buscarlo para fiarle.
        w = tk.Toplevel(self)
        w.title("Editar cliente" if cid else "Agregar cliente")
        w.geometry("1080x760")
        w.minsize(900, 650)
        w.transient(self)
        w.grab_set()
        w.configure(bg="white")

        tk.Label(w, text="Editar cliente" if cid else "AGREGAR CLIENTE", bg="white", fg="#17191d",
                 font=("Segoe UI", 21, "bold")).pack(anchor="w", padx=28, pady=(18, 4))
        tk.Label(w, text="Nombre, datos opcionales y pedido del cliente en un solo lugar.",
                 bg="white", fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(0, 12))

        form = tk.Frame(w, bg="white")
        form.pack(fill="x", padx=28)
        left = tk.Frame(form, bg="white")
        left.pack(fill="x")

        tk.Label(left, text="NOMBRE *", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(left, text="TELEFONO OPCIONAL", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=12)
        tk.Label(left, text="NOTA OPCIONAL", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, sticky="w", padx=12)
        left.grid_columnconfigure(0, weight=3); left.grid_columnconfigure(1, weight=2); left.grid_columnconfigure(2, weight=3)

        name_var = tk.StringVar(value=row[0] if row else "")
        phone_var = tk.StringVar(value=row[1] if row else "")
        name_entry = tk.Entry(left, textvariable=name_var, font=("Segoe UI", 12), relief="solid", bd=1)
        name_entry.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(4, 10), ipady=7)
        tk.Entry(left, textvariable=phone_var, font=("Segoe UI", 12), relief="solid", bd=1).grid(row=1, column=1, sticky="ew", padx=12, pady=(4, 10), ipady=7)
        notes = tk.Entry(left, font=("Segoe UI", 12), relief="solid", bd=1)
        notes.grid(row=1, column=2, sticky="ew", padx=12, pady=(4, 10), ipady=7)
        if row:
            notes.insert(0, row[2] or "")

        # Editar cliente no cambia pedidos; los pedidos se agregan al crear un cliente.
        if cid:
            def save_edit():
                name = name_var.get().strip()
                if not name:
                    messagebox.showwarning("Cliente", "Escribe el nombre del cliente.", parent=w); return
                c = database()
                try:
                    c.execute("UPDATE clientes SET nombre=?,telefono=?,notas=? WHERE id=?",
                              (name, phone_var.get().strip(), notes.get().strip(), cid))
                    c.commit()
                except sqlite3.IntegrityError:
                    c.close(); messagebox.showwarning("Cliente", "Ya existe un cliente con ese nombre.", parent=w); return
                c.close(); w.destroy(); self.show_clients()
            self.make_button(w, "GUARDAR CAMBIOS", save_edit, bg=self.GREEN, fg="white",
                             font=("Segoe UI", 11, "bold")).pack(fill="x", padx=28, pady=14, ipady=9)
            name_entry.focus_set()
            return

        # ---------------- Seleccionar pedido ----------------
        tk.Label(w, text="SELECCIONAR PEDIDO", bg="white", fg="#17191d",
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=28, pady=(4, 5))
        tk.Label(w, text="Busca el producto y toca su tarjeta para agregarlo. Puedes agregar varios.",
                 bg="white", fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(0, 7))

        order_box = tk.Frame(w, bg="#f7f8fa", highlightthickness=1, highlightbackground="#d9dde2")
        order_box.pack(fill="both", expand=True, padx=28, pady=(0, 10))
        order_box.grid_columnconfigure(0, weight=3)
        order_box.grid_columnconfigure(1, weight=2)
        order_box.grid_rowconfigure(1, weight=1)

        tk.Label(order_box, text="PRODUCTOS", bg="#f7f8fa", fg="#333", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(9, 4))
        search_var = tk.StringVar()
        search = tk.Entry(order_box, textvariable=search_var, font=("Segoe UI", 11), relief="solid", bd=1)
        search.grid(row=0, column=0, sticky="e", padx=12, pady=(7, 4), ipadx=6, ipady=5)

        catalog_frame = tk.Frame(order_box, bg="white")
        catalog_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        catalog_frame.grid_rowconfigure(0, weight=1); catalog_frame.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(catalog_frame, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(catalog_frame, orient="vertical", command=canvas.yview)
        cards = tk.Frame(canvas, bg="white")
        canvas_window = canvas.create_window((0, 0), window=cards, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew"); scrollbar.grid(row=0, column=1, sticky="ns")
        cards.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        catalog_frame.bind("<Configure>", lambda e: canvas.itemconfigure(canvas_window, width=max(e.width-2, 400)))

        selected_box = tk.Frame(order_box, bg="white", highlightthickness=1, highlightbackground="#d9dde2")
        selected_box.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        tk.Label(selected_box, text="PEDIDO SELECCIONADO", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(9, 5))
        selected_frame = tk.Frame(selected_box, bg="white")
        selected_frame.pack(fill="both", expand=True, padx=8)
        selected_tree = ttk.Treeview(selected_frame, columns=("producto", "cantidad", "total"), show="headings", selectmode="browse")
        for col, title, width, anchor in [("producto", "Producto", 210, "w"), ("cantidad", "Cant.", 60, "center"), ("total", "Total", 105, "e")]:
            selected_tree.heading(col, text=title); selected_tree.column(col, width=width, anchor=anchor)
        selected_scroll = ttk.Scrollbar(selected_frame, orient="vertical", command=selected_tree.yview)
        selected_tree.configure(yscrollcommand=selected_scroll.set)
        selected_tree.pack(side="left", fill="both", expand=True); selected_scroll.pack(side="right", fill="y")

        selected = {}  # pid -> [name, price, quantity]
        c = database()
        products = c.execute("SELECT id,nombre,precio,imagen FROM productos ORDER BY nombre COLLATE NOCASE,id").fetchall()
        c.close()

        def refresh_order():
            for item in selected_tree.get_children(): selected_tree.delete(item)
            total = 0
            for pid, (name, price, qty) in selected.items():
                line = price * qty; total += line
                selected_tree.insert("", "end", iid=str(pid), values=(name, qty, money(line)))
            total_var.set(money(total))

        def add_selected(pid):
            rowp = next((r for r in products if r[0] == pid), None)
            if not rowp: return
            _pid, name, price, image = rowp
            if pid in selected:
                selected[pid][2] += 1
            else:
                selected[pid] = [name, int(price), 1]
            refresh_order()

        def remove_selected():
            sel = selected_tree.selection()
            if not sel: return
            selected.pop(int(sel[0]), None)
            refresh_order()

        def change_quantity(delta):
            sel = selected_tree.selection()
            if not sel: return
            pid = int(sel[0])
            if pid not in selected: return
            selected[pid][2] += delta
            if selected[pid][2] <= 0: selected.pop(pid, None)
            refresh_order()

        def render_catalog(*_):
            for child in cards.winfo_children(): child.destroy()
            q = normalize(search_var.get())
            rows = [r for r in products if not q or q in normalize(r[1])]
            if not rows:
                tk.Label(cards, text="No se encontraron productos.", bg="white", fg=self.MUTED,
                         font=("Segoe UI", 11, "bold")).pack(pady=30)
                return
            available = max(catalog_frame.winfo_width(), 500)
            cols = max(2, min(4, available // 145))
            for col in range(cols): cards.grid_columnconfigure(col, weight=1, uniform="clientproduct")
            for i, (pid, name, price, image) in enumerate(rows):
                r, col = i // cols, i % cols
                card = tk.Frame(cards, bg="#eef2f5", width=135, height=170,
                                highlightthickness=1, highlightbackground="#dfe4e8", cursor="hand2")
                card.grid(row=r, column=col, padx=6, pady=6, sticky="nsew")
                card.grid_propagate(False)
                photo = self.load_photo(image, 112, 92, f"client-product-{pid}")
                if photo:
                    visual = tk.Label(card, image=photo, bg="#eef2f5"); visual.image = photo
                else:
                    visual = tk.Label(card, text="🖼\nSin imagen", bg="#eef2f5", fg="#8a939d", font=("Segoe UI", 9))
                visual.pack(pady=(6, 3))
                name_label = tk.Label(card, text=name, bg="#eef2f5", fg="#20252b", font=("Segoe UI", 9, "bold"), wraplength=122)
                name_label.pack(pady=(0, 1))
                price_label = tk.Label(card, text=money(price), bg="#eef2f5", fg="#17191d", font=("Segoe UI", 10, "bold"))
                price_label.pack()
                for widget in (card, visual, name_label, price_label):
                    widget.bind("<Button-1>", lambda _e, p=pid: add_selected(p))
            canvas.update_idletasks(); canvas.configure(scrollregion=canvas.bbox("all"))

        search_var.trace_add("write", render_catalog)
        total_var = tk.StringVar(value="$0")
        controls = tk.Frame(selected_box, bg="white")
        controls.pack(fill="x", padx=8, pady=(6, 4))
        self.make_button(controls, "−", lambda: change_quantity(-1), bg="#e9edf1", fg="#252a31", font=("Segoe UI", 11, "bold")).pack(side="left", padx=2, ipady=3, ipadx=7)
        self.make_button(controls, "+", lambda: change_quantity(1), bg="#e9edf1", fg="#252a31", font=("Segoe UI", 11, "bold")).pack(side="left", padx=2, ipady=3, ipadx=7)
        self.make_button(controls, "Eliminar", remove_selected, bg="#ffe7e5", fg="#a5261f", font=("Segoe UI", 9, "bold")).pack(side="left", padx=6, ipady=4, ipadx=5)
        tk.Label(controls, text="TOTAL", bg="white", fg="#333", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 4))
        tk.Label(controls, textvariable=total_var, bg="white", fg="#17191d", font=("Segoe UI", 13, "bold")).pack(side="left")

        def save():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Cliente", "Escribe el nombre del cliente.", parent=w); return
            if not selected:
                messagebox.showwarning("Pedido", "Selecciona al menos un producto que se llevó el cliente.", parent=w); return
            total = sum(item[1] * item[2] for item in selected.values())
            items = ", ".join(f"{item[2]}× {item[0]}" for item in selected.values())
            c = database()
            try:
                c.execute("INSERT INTO clientes(nombre,telefono,notas,creado) VALUES(?,?,?,?)",
                          (name, phone_var.get().strip(), notes.get().strip(), datetime.now().isoformat(sep=" ")))
                new_cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute("INSERT INTO movimientos_clientes(cliente_id,fecha,tipo,monto,concepto) VALUES(?,?,?,?,?)",
                          (new_cid, datetime.now().isoformat(sep=" "), "FIADO", total, items))
                c.commit()
            except sqlite3.IntegrityError:
                c.close(); messagebox.showwarning("Cliente", "Ya existe un cliente con ese nombre.", parent=w); return
            c.close(); w.destroy(); self.show_clients()

        self.make_button(w, "GUARDAR CLIENTE Y FIADO", save, bg="#20242a", fg="white",
                         font=("Segoe UI", 11, "bold")).pack(fill="x", padx=28, pady=(0, 16), ipady=10)
        name_entry.focus_set()
        render_catalog()

    def client_movement(self, movement_type):
        cid = self.selected_client_id()
        if not cid:
            return
        c = database()
        row = c.execute("SELECT nombre FROM clientes WHERE id=?", (cid,)).fetchone()
        balance = self.client_balance(cid, c)
        products = c.execute("SELECT id,nombre,precio FROM productos ORDER BY nombre COLLATE NOCASE").fetchall()
        c.close()
        if not row:
            return
        title = "Registrar fiado" if movement_type == "FIADO" else "Registrar abono"
        w = tk.Toplevel(self)
        w.title(title)
        w.geometry("620x610" if movement_type == "FIADO" else "460x350")
        w.transient(self); w.grab_set(); w.configure(bg="white")
        tk.Label(w, text=title, bg="white", fg="#17191d", font=("Segoe UI", 19, "bold")).pack(pady=(18, 4))
        tk.Label(w, text=f"Cliente: {row[0]}", bg="white", fg=self.MUTED, font=("Segoe UI", 10, "bold")).pack()
        tk.Label(w, text=f"Saldo actual: {money(balance)}", bg="white", fg="#17191d", font=("Segoe UI", 12, "bold")).pack(pady=(6, 12))

        form = tk.Frame(w, bg="white"); form.pack(fill="both", expand=True, padx=28)
        if movement_type == "FIADO":
            tk.Label(form, text="Productos que se lleva", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            list_frame = tk.Frame(form, bg="white"); list_frame.pack(fill="both", expand=True, pady=(4, 8))
            tree = ttk.Treeview(list_frame, columns=("producto","precio","cantidad","total"), show="headings", height=13)
            for col, txt, width, anchor in [("producto","Producto",245,"w"),("precio","Precio",105,"e"),("cantidad","Cantidad",90,"center"),("total","Total",110,"e")]:
                tree.heading(col, text=txt); tree.column(col, width=width, anchor=anchor)
            scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
            tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
            qty_var = tk.StringVar(value="1")
            bottom = tk.Frame(form, bg="white"); bottom.pack(fill="x", pady=(0, 8))
            tk.Label(bottom, text="Cantidad", bg="white", fg="#333", font=("Segoe UI", 9, "bold")).pack(side="left")
            qty_entry = tk.Entry(bottom, textvariable=qty_var, width=7, justify="center", font=("Segoe UI", 11, "bold"), relief="solid", bd=1)
            qty_entry.pack(side="left", padx=6, ipady=4)
            def add_product():
                sel = tree.selection()
                # Selección de catálogo mediante ventana sencilla
                chooser = tk.Toplevel(w); chooser.title("Elegir producto"); chooser.geometry("420x480"); chooser.transient(w); chooser.grab_set(); chooser.configure(bg="white")
                tk.Label(chooser, text="Selecciona el producto", bg="white", font=("Segoe UI", 14, "bold")).pack(pady=12)
                lb = tk.Listbox(chooser, font=("Segoe UI", 11)); lb.pack(fill="both", expand=True, padx=18, pady=8)
                for _, name, price in products: lb.insert("end", f"{name} — {money(price)}")
                def choose():
                    idx = lb.curselection()
                    if not idx: return
                    pid, name, price = products[idx[0]]
                    try: q = max(1, int(qty_var.get()))
                    except ValueError: q = 1
                    iid = str(pid)
                    if tree.exists(iid):
                        old = int(tree.set(iid, "cantidad")); q += old
                    tree.insert("", "end", iid=iid, values=(name, money(price), q, money(price*q))) if not tree.exists(iid) else tree.item(iid, values=(name, money(price), q, money(price*q)))
                    chooser.destroy(); update_total()
                self.make_button(chooser, "AGREGAR", choose, bg="#20242a", fg="white").pack(fill="x", padx=18, pady=12, ipady=8)
            self.make_button(bottom, "＋ Agregar producto", add_product, bg="#20242a", fg="white").pack(side="left", padx=8, ipady=5, ipadx=8)
            total_var = tk.StringVar(value="$0")
            tk.Label(bottom, text="TOTAL:", bg="white", font=("Segoe UI", 10, "bold")).pack(side="right", padx=(8,2))
            tk.Label(bottom, textvariable=total_var, bg="white", fg="#17191d", font=("Segoe UI", 13, "bold")).pack(side="right")
            def update_total():
                total = sum(parse_money(tree.set(i, "total")) for i in tree.get_children())
                total_var.set(money(total))
            tk.Label(form, text="Cada producto queda guardado en el fiado y el saldo se reduce automáticamente con cada abono.", bg="white", fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0,8))
            def save():
                items = []
                total = 0
                for iid in tree.get_children():
                    name = tree.set(iid,"producto"); price = parse_money(tree.set(iid,"precio")); q = int(tree.set(iid,"cantidad")); total += price*q; items.append(f"{q}× {name}")
                if total <= 0: messagebox.showwarning("Fiado", "Agrega al menos un producto.", parent=w); return
                c = database(); c.execute("INSERT INTO movimientos_clientes(cliente_id,fecha,tipo,monto,concepto) VALUES(?,?,?,?,?)", (cid, datetime.now().isoformat(sep=" "), "FIADO", total, ", ".join(items))); c.commit(); c.close(); w.destroy(); self.show_clients()
            self.make_button(w, "GUARDAR FIADO", save, bg="#20242a", fg="white").pack(fill="x", padx=28, pady=(0,18), ipady=9)
        else:
            tk.Label(form, text="Monto del abono", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            amount_var = tk.StringVar(value="0")
            amount_entry = tk.Entry(form, textvariable=amount_var, font=("Segoe UI", 13, "bold"), justify="right", relief="solid", bd=1)
            amount_entry.pack(fill="x", ipady=7, pady=(3, 10))
            tk.Label(form, text="Concepto (opcional)", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            concept_var = tk.StringVar()
            tk.Entry(form, textvariable=concept_var, font=("Segoe UI", 11), relief="solid", bd=1).pack(fill="x", ipady=7, pady=(3, 14))
            def save():
                amount = parse_money(amount_var.get())
                if amount <= 0: messagebox.showwarning("Monto", "Escribe un monto mayor que cero.", parent=w); return
                if amount > balance: messagebox.showwarning("Abono", "El abono no puede ser mayor que lo que debe el cliente.", parent=w); return
                c = database(); c.execute("INSERT INTO movimientos_clientes(cliente_id,fecha,tipo,monto,concepto) VALUES(?,?,?,?,?)", (cid, datetime.now().isoformat(sep=" "), "ABONO", amount, concept_var.get().strip())); c.commit(); c.close(); w.destroy(); self.show_clients()
            self.make_button(w, "GUARDAR ABONO", save, bg=self.GREEN, fg="white").pack(fill="x", padx=30, ipady=9)
            amount_entry.focus_set()

    def show_client_movements(self):
        cid = self.selected_client_id()
        if not cid:
            return
        c = database()
        client = c.execute("SELECT nombre FROM clientes WHERE id=?", (cid,)).fetchone()
        rows = c.execute("SELECT id,fecha,tipo,monto,concepto FROM movimientos_clientes WHERE cliente_id=? ORDER BY id DESC", (cid,)).fetchall()
        balance = self.client_balance(cid, c)
        c.close()
        if not client:
            return
        w = tk.Toplevel(self)
        w.title(f"Movimientos - {client[0]}")
        w.geometry("760x500")
        w.transient(self)
        w.configure(bg="white")
        tk.Label(w, text=f"Movimientos de {client[0]}", bg="white", fg="#17191d", font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(w, text=f"Saldo pendiente: {money(balance)}", bg="white", fg="#17191d", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(0, 10))
        frame = tk.Frame(w, bg="white")
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        tree = ttk.Treeview(frame, columns=("fecha","tipo","monto","concepto"), show="headings")
        for col, title, width, anchor in [("fecha","Fecha",155,"w"),("tipo","Movimiento",120,"center"),("monto","Monto",140,"e"),("concepto","Concepto",280,"w")]:
            tree.heading(col, text=title); tree.column(col, width=width, anchor=anchor)
        for _id, fecha, tipo, monto, concepto in rows:
            try: fecha = datetime.fromisoformat(fecha).strftime("%d/%m/%Y %I:%M %p")
            except Exception: pass
            tree.insert("", "end", values=(fecha, "Fiado" if tipo == "FIADO" else "Abono", money(monto), concepto or "—"))
        tree.pack(fill="both", expand=True)

    def delete_client(self):
        cid = self.selected_client_id()
        if not cid:
            return
        c = database()
        row = c.execute("SELECT nombre FROM clientes WHERE id=?", (cid,)).fetchone()
        balance = self.client_balance(cid, c)
        c.close()
        if not row:
            return
        if balance > 0:
            messagebox.showwarning("Cliente", f"No puedes eliminar a {row[0]} porque todavía debe {money(balance)}.", parent=self)
            return
        if not messagebox.askyesno("Eliminar cliente", f"¿Eliminar a {row[0]} y su historial?", parent=self):
            return
        c = database()
        c.execute("DELETE FROM clientes WHERE id=?", (cid,))
        c.commit(); c.close()
        self.show_clients()

    # --------------------------- Settings ----------------------------------
    def show_settings(self):
        self.current_view = "settings"
        self.clear_body()
        tk.Label(self.body, text="Configuración", bg=self.BG, fg="#17191d",
                 font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(2, 8))
        card = tk.Frame(self.body, bg="white")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(card, text="Nombre del negocio", bg="white", fg="#333", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(12, 4))
        business_var = tk.StringVar(value=self.config_data.get("negocio", "MI NEGOCIO"))
        business_entry = tk.Entry(card, textvariable=business_var, font=("Segoe UI", 12), relief="solid", bd=1)
        business_entry.pack(fill="x", padx=18, ipady=6)
        self.make_button(card, "Guardar nombre", lambda: self.save_business_name(business_var.get()),
                         bg=self.GREEN, fg="white").pack(anchor="w", padx=18, pady=10, ipady=6, ipadx=10)

        tk.Label(self.body, text="Imágenes de billetes / monedas", bg=self.BG, fg="#17191d",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(4, 3))
        tk.Label(self.body, text="Cambia las imágenes aquí. Se guardan en datos/dinero y permanecen después de reiniciar.",
                 bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))

        # Las siete denominaciones se muestran en una cuadrícula compacta.
        # $100.000 siempre tiene su propio botón y no queda oculto.
        money_frame = tk.Frame(self.body, bg=self.BG)
        money_frame.pack(fill="both", expand=True, padx=2)
        for col in range(4):
            money_frame.grid_columnconfigure(col, weight=1, uniform="money")
        for i, d in enumerate(DENOMINATIONS):
            row, col = divmod(i, 4)
            card = tk.Frame(money_frame, bg="white", highlightthickness=1, highlightbackground="#e0e4e8")
            card.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            tk.Label(card, text=money(d), bg="white", fg="#252a31",
                     font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 3))
            preview = tk.Label(card, text="Sin imagen personalizada", bg="#f0f2f4", fg="#7a828a",
                               width=20, height=3, anchor="center")
            preview.pack(fill="x", padx=8, pady=(0, 6))
            rel = self.money_paths.get(d, "")
            if rel:
                ph = self.load_photo(rel, 210, 68, f"settings-{d}")
                if ph:
                    preview.config(image=ph, text="")
                    preview.image = ph
            self.make_button(card, "Cambiar imagen", lambda value=d: self.change_money_image(value),
                             bg="#e9edf1", fg="#252a31").pack(fill="x", padx=8, pady=(0, 8), ipady=5)

    def save_business_name(self, name):
        name = name.strip() or "MI NEGOCIO"
        self.config_data["negocio"] = name
        save_config(self.config_data)
        self.business_label.config(text=name)
        self.show_settings()

    def change_money_image(self, denomination):
        path = filedialog.askopenfilename(filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
        if not path:
            return
        try:
            relative = copy_image(path, MONEY, f"dinero_{denomination}")
            old = self.money_paths.get(denomination, "")
            self.money_paths[denomination] = relative
            self.config_data["dinero"] = {str(k): v for k, v in self.money_paths.items()}
            save_config(self.config_data)
            # La copia nueva es permanente y se muestra inmediatamente.
            if old:
                safe_remove_image(old)
            self.show_settings()
        except Exception as exc:
            messagebox.showerror("Imagen", f"No se pudo guardar la imagen.\n{exc}")

    # --------------------------- Navigation helpers ------------------------
    def refresh_current_view(self):
        if self.current_view == "sale":
            self.show_sale()
        elif self.current_view == "manager":
            self.show_manager()
        elif self.current_view == "settings":
            self.show_settings()
        elif self.current_view == "clients":
            self.show_clients()
        else:
            self.show_sale()


if __name__ == "__main__":
    database().close()
    app = App()
    app.mainloop()
