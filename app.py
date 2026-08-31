import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
from datetime import datetime, timedelta

DB="ventas.db"
DENOMS=[1000,2000,5000,10000,20000,50000,100000]
CATS=["Todos","Cargadores","Juguetes","Gorras","Cables","Otros"]

def money(n): return "$"+f"{int(n):,}".replace(",",".")

def db():
    c=sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY,nombre TEXT,categoria TEXT,precio INTEGER,imagen TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS ventas(id INTEGER PRIMARY KEY AUTOINCREMENT,fecha TEXT,total INTEGER,recibido INTEGER,cambio INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS detalle(id INTEGER PRIMARY KEY AUTOINCREMENT,venta_id INTEGER,nombre TEXT,cantidad INTEGER,precio INTEGER)")
    if c.execute("SELECT COUNT(*) FROM productos").fetchone()[0]==0:
        c.executemany("INSERT INTO productos(nombre,categoria,precio,imagen) VALUES(?,?,?,?)",[
            ("Cargador V8","Cargadores",10000,""),("Cargador Tipo C","Cargadores",12000,""),
            ("Cargador iPhone","Cargadores",15000,""),("Gorra","Gorras",25000,""),("Muñeca","Juguetes",25000,"")])
    c.commit(); return c

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("Registro de Ventas"); self.geometry("1250x760"); self.configure(bg="#f3f5f7")
        self.cart={}; self.received=0; self.business="MI NEGOCIO"; self.den_images={}
        self.build(); self.load_products(); self.refresh()

    def build(self):
        top=tk.Frame(self,bg="#17191d",height=70); top.pack(fill="x")
        self.brand=tk.Label(top,text="🏪  MI NEGOCIO",bg="#17191d",fg="white",font=("Segoe UI",22,"bold")); self.brand.pack(side="left",padx=25,pady=17)
        tk.Button(top,text="⚙ Configuración",command=self.settings,bg="#30343a",fg="white",relief="flat").pack(side="right",padx=20,pady=18)
        nav=tk.Frame(self,bg="white"); nav.pack(fill="x")
        tk.Button(nav,text="🛒 Nueva venta",command=self.show_sale,relief="flat",font=("Segoe UI",11,"bold")).pack(side="left",padx=18,pady=8)
        tk.Button(nav,text="📊 Ventas realizadas",command=self.history,relief="flat",font=("Segoe UI",11,"bold")).pack(side="left",pady=8)
        self.content=tk.Frame(self,bg="#f3f5f7"); self.content.pack(fill="both",expand=True,padx=16,pady=14); self.show_sale()

    def clear(self):
        for w in self.content.winfo_children(): w.destroy()

    def show_sale(self):
        self.clear()
        left=tk.Frame(self.content,bg="white"); left.pack(side="left",fill="both",expand=True,padx=(0,10))
        right=tk.Frame(self.content,bg="white",width=320); right.pack(side="right",fill="y"); right.pack_propagate(False)
        tk.Label(left,text="Nueva venta",bg="white",font=("Segoe UI",20,"bold")).pack(anchor="w",padx=18,pady=(16,5))
        sf=tk.Frame(left,bg="white"); sf.pack(fill="x",padx=18,pady=8)
        self.q=tk.StringVar(); e=tk.Entry(sf,textvariable=self.q,font=("Segoe UI",13)); e.pack(side="left",fill="x",expand=True,ipady=9); e.bind("<KeyRelease>",lambda _:self.load_products())
        tk.Button(sf,text="🔎 Buscar",command=self.load_products,relief="flat",bg="#e8eaed").pack(side="left",padx=8,ipady=7)
        cf=tk.Frame(left,bg="white"); cf.pack(fill="x",padx=12)
        for cat in CATS: tk.Button(cf,text=cat,command=lambda c=cat:self.load_products(c),relief="flat",bg="#eef0f3").pack(side="left",padx=3)
        self.products=tk.Frame(left,bg="white"); self.products.pack(fill="x",padx=12,pady=6)
        tk.Label(left,text="Venta actual",bg="white",font=("Segoe UI",14,"bold")).pack(anchor="w",padx=18,pady=(8,5))
        self.table=ttk.Treeview(left,columns=("p","q","price","sub"),show="headings",height=10)
        for a,b,w in [("p","Producto",250),("q","Cantidad",80),("price","Precio",110),("sub","Subtotal",130)]: self.table.heading(a,text=b); self.table.column(a,width=w,anchor="center")
        self.table.pack(fill="both",expand=True,padx=18); tk.Button(left,text="Eliminar seleccionado",command=self.remove,relief="flat").pack(anchor="e",padx=18,pady=8)

        tk.Label(right,text="COBRO",bg="white",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=18,pady=(18,6))
        self.total_label=tk.Label(right,text="TOTAL  $0",bg="white",font=("Segoe UI",24,"bold")); self.total_label.pack(anchor="w",padx=18)
        tk.Label(right,text="Dinero recibido (pulsa las denominaciones)",bg="white").pack(anchor="w",padx=18,pady=(12,4))
        self.received_label=tk.Label(right,text="$0",bg="white",font=("Segoe UI",20,"bold")); self.received_label.pack(anchor="w",padx=18)
        self.money_buttons=tk.Frame(right,bg="white"); self.money_buttons.pack(fill="x",padx=10,pady=10); self.build_money_buttons()
        tk.Button(right,text="Borrar dinero recibido",command=self.clear_received,relief="flat").pack(anchor="w",padx=18)
        self.change_label=tk.Label(right,text="CAMBIO  $0",bg="white",fg="#16834b",font=("Segoe UI",20,"bold")); self.change_label.pack(anchor="w",padx=18,pady=12)
        tk.Button(right,text="REGISTRAR VENTA",command=self.save_sale,bg="#39a866",fg="white",relief="flat",font=("Segoe UI",12,"bold"),height=2).pack(fill="x",padx=18,pady=6)
        tk.Button(right,text="Cancelar / nueva venta",command=self.new_sale,relief="flat").pack(fill="x",padx=18)

    def build_money_buttons(self):
        for w in self.money_buttons.winfo_children(): w.destroy()
        for d in DENOMS:
            text=("🪙 " if d==1000 else "💵 ")+money(d)
            tk.Button(self.money_buttons,text=text,command=lambda x=d:self.add_cash(x),relief="flat",bg="#eef0f3",anchor="w").pack(fill="x",pady=2)

    def load_products(self,cat="Todos"):
        if not hasattr(self,"products"): return
        for w in self.products.winfo_children(): w.destroy()
        q=self.q.get().strip().lower()
        c=db(); rows=c.execute("SELECT id,nombre,categoria,precio,imagen FROM productos ORDER BY nombre").fetchall(); c.close()
        rows=[r for r in rows if (cat=="Todos" or r[2]==cat) and (not q or q in r[1].lower())]
        for pid,n,ca,p,img in rows[:12]:
            tk.Button(self.products,text=f"{n}\n{money(p)}",command=lambda pid=pid:self.add_product(pid),relief="flat",bg="#eef0f3",font=("Segoe UI",10,"bold"),width=17,height=3).pack(side="left",padx=4,pady=4)
        if q and not rows:
            tk.Button(self.products,text=f'No existe "{self.q.get()}"\n＋ AGREGAR PRODUCTO',command=self.add_product_window,relief="flat",bg="#fff0cf",font=("Segoe UI",10,"bold"),width=23,height=3).pack(side="left",padx=4,pady=4)

    def add_product(self,pid):
        c=db(); r=c.execute("SELECT nombre,precio FROM productos WHERE id=?",(pid,)).fetchone(); c.close()
        if not r:return
        n,p=r
        if pid in self.cart:self.cart[pid][2]+=1
        else:self.cart[pid]=[n,p,1]
        self.refresh()

    def remove(self):
        s=self.table.selection()
        if not s:return
        pid=int(self.table.item(s[0],"tags")[0]); self.cart[pid][2]-=1
        if self.cart[pid][2]<=0: del self.cart[pid]
        self.refresh()

    def refresh(self):
        if not hasattr(self,"table"): return
        for x in self.table.get_children(): self.table.delete(x)
        total=0
        for pid,(n,p,q) in self.cart.items():
            total+=p*q; self.table.insert("", "end",values=(n,q,money(p),money(p*q)),tags=(str(pid),))
        self.total_label.config(text=f"TOTAL  {money(total)}"); self.pay_refresh()

    def add_cash(self,d): self.received+=d; self.pay_refresh()
    def clear_received(self): self.received=0; self.pay_refresh()

    def pay_refresh(self):
        total=sum(p*q for _,p,q in self.cart.values()); diff=self.received-total
        self.received_label.config(text=money(self.received))
        self.change_label.config(text=("CAMBIO  "+money(diff)) if diff>=0 else ("FALTA  "+money(-diff)),fg="#16834b" if diff>=0 else "#b22")

    def new_sale(self): self.cart={}; self.received=0; self.refresh()

    def save_sale(self):
        if not self.cart:return messagebox.showwarning("Venta","Agrega al menos un producto.")
        total=sum(p*q for _,p,q in self.cart.values())
        if self.received<total:return messagebox.showwarning("Pago","El dinero recibido no alcanza.")
        c=db();cur=c.cursor();cur.execute("INSERT INTO ventas(fecha,total,recibido,cambio) VALUES(?,?,?,?)",(datetime.now().isoformat(timespec="seconds"),total,self.received,self.received-total));vid=cur.lastrowid
        cur.executemany("INSERT INTO detalle(venta_id,nombre,cantidad,precio) VALUES(?,?,?,?)",[(vid,n,q,p) for n,p,q in self.cart.values()]);c.commit();c.close()
        messagebox.showinfo("Venta registrada",f"Venta #{vid}\nTotal: {money(total)}\nRecibido: {money(self.received)}\nCambio: {money(self.received-total)}")
        self.cart={}; self.received=0; self.refresh()

    def history(self):
        w=tk.Toplevel(self);w.title("Ventas realizadas");w.geometry("950x620");w.configure(bg="#f3f5f7")
        tk.Label(w,text="📊 Ventas realizadas",bg="#f3f5f7",font=("Segoe UI",20,"bold")).pack(anchor="w",padx=20,pady=18)
        c=db();now=datetime.now();day=now.replace(hour=0,minute=0,second=0,microsecond=0);week=day-timedelta(days=day.weekday());month=day.replace(day=1)
        sf=tk.Frame(w,bg="#f3f5f7");sf.pack(fill="x",padx=15)
        for title,start in [("HOY",day),("ESTA SEMANA",week),("ESTE MES",month)]:
            total,count=c.execute("SELECT COALESCE(SUM(total),0),COUNT(*) FROM ventas WHERE fecha>=?",(start.isoformat(),)).fetchone()
            b=tk.Frame(sf,bg="white",height=75);b.pack(side="left",fill="both",expand=True,padx=5);b.pack_propagate(False)
            tk.Label(b,text=title,bg="white",font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=(10,0));tk.Label(b,text=f"{money(total)} • {count} ventas",bg="white",font=("Segoe UI",14,"bold")).pack(anchor="w",padx=12)
        tree=ttk.Treeview(w,columns=("id","date","total","received","change"),show="headings",height=17)
        for a,b in [("id","Venta"),("date","Fecha y hora"),("total","Total"),("received","Recibido"),("change","Cambio")]:tree.heading(a,text=b);tree.column(a,width=170,anchor="center")
        tree.pack(fill="both",expand=True,padx=20,pady=15)
        for row in c.execute("SELECT id,fecha,total,recibido,cambio FROM ventas ORDER BY id DESC"):
            tree.insert("", "end",values=(row[0],datetime.fromisoformat(row[1]).strftime("%d/%m/%Y %H:%M"),money(row[2]),money(row[3]),money(row[4])),tags=(str(row[0]),))
        c.close()
        def detail(_=None):
            s=tree.selection()
            if not s:return
            vid=int(tree.item(s[0],"tags")[0]);c=db();rows=c.execute("SELECT nombre,cantidad,precio FROM detalle WHERE venta_id=?",(vid,)).fetchall();c.close()
            messagebox.showinfo(f"Venta #{vid}","\n".join(f"{n}  x{q}  {money(p)}" for n,q,p in rows))
        tree.bind("<Double-1>",detail)
        tk.Label(w,text="Doble clic en una venta para ver sus productos, cantidades y precios.",bg="#f3f5f7").pack(pady=4)

    def add_product_window(self):
        w=tk.Toplevel(self);w.title("Agregar producto");w.geometry("430x350")
        tk.Label(w,text="Agregar producto",font=("Segoe UI",18,"bold")).pack(pady=15)
        es=[]
        for lab in ["Nombre","Categoría","Precio"]:
            tk.Label(w,text=lab).pack(anchor="w",padx=25);e=tk.Entry(w);e.pack(fill="x",padx=25,pady=4);es.append(e)
        path=tk.StringVar(value="Sin imagen")
        tk.Button(w,text="🖼 Agregar imagen del producto",command=lambda:path.set(filedialog.askopenfilename(filetypes=[("Imágenes","*.png *.gif *.ppm *.pgm")]) or "Sin imagen")).pack(pady=10)
        tk.Label(w,textvariable=path,wraplength=370).pack()
        def save():
            n=es[0].get().strip();ca=es[1].get().strip() or "Otros"
            try:p=int(es[2].get().replace(".","").replace("$",""))
            except:return messagebox.showerror("Error","Precio inválido.")
            if not n:return messagebox.showerror("Error","Escribe el nombre.")
            c=db();c.execute("INSERT INTO productos(nombre,categoria,precio,imagen) VALUES(?,?,?,?)",(n,ca,p,path.get() if path.get()!="Sin imagen" else ""));c.commit();c.close();w.destroy();self.load_products()
        tk.Button(w,text="Guardar producto",command=save,bg="#39a866",fg="white",relief="flat").pack(pady=15)

    def settings(self):
        w=tk.Toplevel(self);w.title("Configuración");w.geometry("560x620")
        tk.Label(w,text="Configuración",font=("Segoe UI",19,"bold")).pack(pady=15)
        tk.Label(w,text="Nombre del negocio").pack(anchor="w",padx=25)
        name=tk.Entry(w);name.pack(fill="x",padx=25,pady=6);name.insert(0,self.business)
        tk.Label(w,text="Imágenes de monedas y billetes",font=("Segoe UI",13,"bold")).pack(anchor="w",padx=25,pady=(12,6))
        for d in DENOMS:
            row=tk.Frame(w);row.pack(fill="x",padx=18,pady=3)
            tk.Label(row,text=money(d),width=10).pack(side="left")
            status=tk.Label(row,text=self.den_images.get(d,"Sin imagen"),anchor="w");status.pack(side="left",fill="x",expand=True)
            def choose(d=d,status=status):
                p=filedialog.askopenfilename(filetypes=[("Imágenes","*.png *.gif *.ppm *.pgm")])
                if p:self.den_images[d]=p;status.config(text=p)
            tk.Button(row,text="Agregar / cambiar imagen",command=choose,relief="flat").pack(side="right")
        def save():
            self.business=name.get().strip() or "MI NEGOCIO";self.brand.config(text="🏪  "+self.business);w.destroy()
        tk.Button(w,text="Guardar",command=save,bg="#39a866",fg="white",relief="flat").pack(pady=18)

db();App().mainloop()
