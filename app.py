
import shutil, sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

BASE=Path(__file__).resolve().parent
DATA=BASE/"datos"; PRODUCTS=DATA/"productos"; MONEY=DATA/"dinero"; DB=DATA/"ventas.db"
for p in (PRODUCTS,MONEY): p.mkdir(parents=True,exist_ok=True)
D=[1000,2000,5000,10000,20000,50000,100000]
DEFAULT=["Cargadores","Gorras","Radios","Memorias","Audífonos","Bolsos","Gorros","Juguetes","Otros"]

def M(n): return "$"+f"{int(n):,}".replace(",",".")

def con():
    c=sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS categorias(id INTEGER PRIMARY KEY,nombre TEXT UNIQUE)")
    c.execute("CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY,nombre TEXT,categoria TEXT,precio INTEGER,imagen TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS ventas(id INTEGER PRIMARY KEY AUTOINCREMENT,fecha TEXT,total INTEGER,recibido INTEGER,cambio INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS detalle(id INTEGER PRIMARY KEY AUTOINCREMENT,venta_id INTEGER,nombre TEXT,cantidad INTEGER,precio INTEGER)")
    for x in DEFAULT: c.execute("INSERT OR IGNORE INTO categorias(nombre) VALUES(?)",(x,))
    c.commit(); return c

def copyimg(src,dst,prefix):
    if not src:return ""
    s=Path(src); ext=s.suffix.lower()
    if ext not in [".jpg",".jpeg",".png",".gif",".bmp",".webp"]: return ""
    target=dst/(prefix+"_"+datetime.now().strftime("%Y%m%d%H%M%S%f")+ext)
    shutil.copy2(s,target); return str(target.relative_to(BASE))

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("Registro de Ventas"); self.geometry("1250x780"); self.configure(bg="#f2f4f7")
        self.cart={}; self.received=0; self.cat="Todos"; self.cache={}; self.money={}
        self.top(); self.sale()

    def top(self):
        h=tk.Frame(self,bg="#17191d",height=68); h.pack(fill="x")
        b=tk.Button(h,text="☰  MI NEGOCIO",command=self.menu,bg="#17191d",fg="white",relief="flat",font=("Segoe UI",20,"bold"))
        b.pack(side="left",padx=18,pady=12)
        tk.Button(h,text="⚙",command=self.settings,bg="#30343a",fg="white",relief="flat",font=("Segoe UI",13,"bold")).pack(side="right",padx=18,pady=14)
        self.body=tk.Frame(self,bg="#f2f4f7"); self.body.pack(fill="both",expand=True,padx=14,pady=14)

    def clear(self):
        for w in self.body.winfo_children():w.destroy()

    def menu(self):
        w=tk.Toplevel(self);w.title("Menú");w.geometry("310x420");w.configure(bg="white")
        tk.Label(w,text="MENÚ",bg="white",font=("Segoe UI",19,"bold")).pack(pady=18)
        items=[("🛒 Nueva venta",self.sale),("📊 Ventas de hoy",lambda:self.history("Hoy")),("📅 Ventas de esta semana",lambda:self.history("Semana")),("📆 Ventas de este mes",lambda:self.history("Mes")),("📦 Productos y categorías",self.manager),("⚙ Configuración",self.settings)]
        for text,cmd in items:
            tk.Button(w,text=text,command=lambda c=cmd:(w.destroy(),c()),anchor="w",relief="flat",bg="#eef0f3",font=("Segoe UI",11)).pack(fill="x",padx=20,pady=5,ipady=7)

    def sale(self):
        self.clear()
        left=tk.Frame(self.body,bg="white");left.pack(side="left",fill="both",expand=True,padx=(0,9))
        right=tk.Frame(self.body,bg="white",width=340);right.pack(side="right",fill="y");right.pack_propagate(False)
        tk.Label(left,text="Nueva venta",bg="white",font=("Segoe UI",21,"bold")).pack(anchor="w",padx=18,pady=(15,4))
        sf=tk.Frame(left,bg="white");sf.pack(fill="x",padx=18,pady=5)
        self.q=tk.StringVar();e=tk.Entry(sf,textvariable=self.q,font=("Segoe UI",13));e.pack(side="left",fill="x",expand=True,ipady=9);e.bind("<KeyRelease>",lambda _:self.products())
        tk.Button(sf,text="🔎 Buscar",command=self.products,relief="flat",bg="#e8eaed").pack(side="left",padx=6,ipady=7)
        self.cats=tk.Frame(left,bg="white");self.cats.pack(fill="x",padx=12,pady=3)
        self.grid=tk.Frame(left,bg="white");self.grid.pack(fill="both",expand=True,padx=12)
        tk.Label(right,text="VENTA ACTUAL",bg="white",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=15,pady=12)
        self.tree=ttk.Treeview(right,columns=("item","sub"),show="headings",height=10);self.tree.heading("item",text="Producto / Cant.");self.tree.heading("sub",text="Subtotal");self.tree.column("item",width=205);self.tree.column("sub",width=100,anchor="e");self.tree.pack(fill="x",padx=10)
        tk.Button(right,text="Eliminar seleccionado",command=self.remove,relief="flat").pack(anchor="e",padx=10,pady=5)
        self.total=tk.Label(right,text="TOTAL  $0",bg="white",font=("Segoe UI",22,"bold"));self.total.pack(anchor="w",padx=15,pady=4)
        tk.Label(right,text="DINERO RECIBIDO",bg="white").pack(anchor="w",padx=15)
        self.rec=tk.Label(right,text="$0",bg="white",font=("Segoe UI",19,"bold"));self.rec.pack(anchor="w",padx=15)
        self.cash=tk.Frame(right,bg="white");self.cash.pack(fill="x",padx=8,pady=5)
        self.cashbuttons()
        self.change=tk.Label(right,text="CAMBIO  $0",bg="white",font=("Segoe UI",19,"bold"));self.change.pack(anchor="w",padx=15,pady=6)
        tk.Button(right,text="Borrar dinero recibido",command=lambda:self.setrec(0),relief="flat").pack(anchor="w",padx=15)
        tk.Button(right,text="✓  REGISTRAR VENTA",command=self.save,bg="#39a866",fg="white",relief="flat",font=("Segoe UI",12,"bold"),height=2).pack(fill="x",padx=15,pady=8)
        tk.Button(right,text="Cancelar / nueva venta",command=self.new,relief="flat").pack(fill="x",padx=15)
        self.loadcats();self.products()

    def loadcats(self):
        for w in self.cats.winfo_children():w.destroy()
        c=con();cats=[x[0] for x in c.execute("SELECT nombre FROM categorias ORDER BY id")];c.close()
        for x in ["Todos"]+cats:
            tk.Button(self.cats,text=x,command=lambda y=x:self.choosecat(y),relief="flat",bg="#dfe4e8" if x==self.cat else "#eef0f3",font=("Segoe UI",9,"bold")).pack(side="left",padx=2,pady=2,ipadx=4,ipady=3)
        tk.Button(self.cats,text="＋ Categoría",command=self.addcat,relief="flat",bg="#fff0cf").pack(side="left",padx=3)

    def choosecat(self,x):self.cat=x;self.loadcats();self.products()

    def products(self):
        if not hasattr(self,"grid"):return
        for w in self.grid.winfo_children():w.destroy()
        q=self.q.get().lower().strip();c=con()
        rows=c.execute("SELECT id,nombre,categoria,precio,imagen FROM productos ORDER BY nombre").fetchall();c.close()
        rows=[r for r in rows if (self.cat=="Todos" or r[2]==self.cat) and (not q or q in r[1].lower())]
        if not rows and q:
            tk.Button(self.grid,text=f'No existe "{self.q.get()}"\n＋ AGREGAR PRODUCTO',command=self.addproduct,relief="flat",bg="#fff0cf",font=("Segoe UI",11,"bold"),height=4).pack(anchor="w",padx=8,pady=10);return
        for i,(pid,n,cat,p,img) in enumerate(rows):
            card=tk.Frame(self.grid,bg="#eef0f3",width=180,height=190);card.grid(row=i//4,column=i%4,padx=6,pady=6);card.grid_propagate(False)
            photo=self.photo(img,145,110,"p"+str(pid))
            lab=tk.Label(card,image=photo,bg="#eef0f3") if photo else tk.Label(card,text="🖼\nSin imagen",bg="#eef0f3",font=("Segoe UI",10))
            if photo:lab.image=photo
            lab.pack(pady=(7,2));tk.Label(card,text=n,bg="#eef0f3",font=("Segoe UI",10,"bold"),wraplength=165).pack();tk.Label(card,text=M(p),bg="#eef0f3",font=("Segoe UI",11,"bold")).pack()
            for z in (card,lab):z.bind("<Button-1>",lambda e,x=pid:self.add(x))

    def photo(self,rel,w,h,key):
        if not rel:return None
        p=BASE/rel
        if not p.exists():return None
        try:
            im=Image.open(p).convert("RGB");im.thumbnail((w,h));ph=ImageTk.PhotoImage(im);self.cache[key]=ph;return ph
        except:return None

    def add(self,pid):
        c=con();r=c.execute("SELECT nombre,precio FROM productos WHERE id=?",(pid,)).fetchone();c.close()
        if not r:return
        if pid in self.cart:self.cart[pid][2]+=1
        else:self.cart[pid]=[r[0],r[1],1]
        self.refresh()

    def remove(self):
        s=self.tree.selection()
        if not s:return
        pid=int(self.tree.item(s[0],"tags")[0]);self.cart[pid][2]-=1
        if self.cart[pid][2]<=0:del self.cart[pid]
        self.refresh()

    def refresh(self):
        for x in self.tree.get_children():self.tree.delete(x)
        total=0
        for pid,(n,p,q) in self.cart.items():total+=p*q;self.tree.insert("", "end",values=(f"{n}  x{q}",M(p*q)),tags=(str(pid),))
        self.total.config(text=f"TOTAL  {M(total)}");self.pay()

    def cashbuttons(self):
        for w in self.cash.winfo_children():w.destroy()
        for i,d in enumerate(D):
            rel=self.money.get(d,"");ph=self.photo(rel,125,45,"m"+str(d)) if rel else None
            b=tk.Button(self.cash,image=ph,text=M(d) if not ph else "",compound="center",command=lambda x=d:self.setrec(self.received+x),relief="flat",bg="#eef0f3")
            if ph:b.image=ph
            b.grid(row=i//2,column=i%2,sticky="ew",padx=2,pady=2)
        self.cash.grid_columnconfigure(0,weight=1);self.cash.grid_columnconfigure(1,weight=1)

    def setrec(self,n):self.received=n;self.pay()
    def pay(self):
        self.received=getattr(self,"received",0);total=sum(p*q for _,p,q in self.cart.values());d=self.received-total
        self.rec.config(text=M(self.received));self.change.config(text=("CAMBIO  "+M(d)) if d>=0 else ("FALTA  "+M(-d)),fg="#16834b" if d>=0 else "#b22")
    def new(self):self.cart={};self.received=0;self.refresh()

    def save(self):
        if not self.cart:return messagebox.showwarning("Venta","Agrega un producto.")
        total=sum(p*q for _,p,q in self.cart.values())
        if self.received<total:return messagebox.showwarning("Pago","El dinero recibido no alcanza.")
        c=con();cur=c.cursor();cur.execute("INSERT INTO ventas(fecha,total,recibido,cambio) VALUES(?,?,?,?)",(datetime.now().isoformat(timespec="seconds"),total,self.received,self.received-total));vid=cur.lastrowid
        cur.executemany("INSERT INTO detalle(venta_id,nombre,cantidad,precio) VALUES(?,?,?,?)",[(vid,n,q,p) for n,p,q in self.cart.values()]);c.commit();c.close()
        messagebox.showinfo("Venta registrada",f"Venta #{vid}\nTotal: {M(total)}\nRecibido: {M(self.received)}\nCambio: {M(self.received-total)}")
        self.new()

    def history(self,period="Hoy"):
        w=tk.Toplevel(self);w.title("Ventas");w.geometry("1000x650");w.configure(bg="#f2f4f7")
        tk.Label(w,text="📊 Ventas",bg="#f2f4f7",font=("Segoe UI",21,"bold")).pack(anchor="w",padx=20,pady=15)
        c=con();now=datetime.now();day=now.replace(hour=0,minute=0,second=0,microsecond=0);week=day-timedelta(days=day.weekday());month=day.replace(day=1)
        for title,start in [("HOY",day),("SEMANA",week),("MES",month)]:
            total,count=c.execute("SELECT COALESCE(SUM(total),0),COUNT(*) FROM ventas WHERE fecha>=?",(start.isoformat(),)).fetchone()
            tk.Label(w,text=f"{title}: {M(total)}   •   {count} ventas",bg="white",font=("Segoe UI",13,"bold")).pack(fill="x",padx=20,pady=3,ipady=8)
        t=tk.Frame(w,bg="#f2f4f7");t.pack(fill="both",expand=True,padx=20,pady=12)
        tree=ttk.Treeview(t,columns=("id","fecha","total","rec","cam"),show="headings")
        for a,b in [("id","Venta"),("fecha","Fecha y hora"),("total","Total"),("rec","Recibido"),("cam","Cambio")]:tree.heading(a,text=b);tree.column(a,width=180,anchor="center")
        tree.pack(fill="both",expand=True)
        for r in c.execute("SELECT id,fecha,total,recibido,cambio FROM ventas ORDER BY id DESC"):
            tree.insert("", "end",values=(r[0],datetime.fromisoformat(r[1]).strftime("%d/%m/%Y %H:%M"),M(r[2]),M(r[3]),M(r[4])),tags=(str(r[0]),))
        c.close()
        def det(_=None):
            s=tree.selection()
            if not s:return
            vid=int(tree.item(s[0],"tags")[0]);cc=con();rs=cc.execute("SELECT nombre,cantidad,precio FROM detalle WHERE venta_id=?",(vid,)).fetchall();cc.close()
            messagebox.showinfo("Detalle de venta","\n".join(f"{n} x{q} — {M(p)}" for n,q,p in rs))
        tree.bind("<Double-1>",det)

    def manager(self):
        w=tk.Toplevel(self);w.title("Productos");w.geometry("750x550")
        tk.Label(w,text="Productos y categorías",font=("Segoe UI",18,"bold")).pack(pady=15)
        t=ttk.Treeview(w,columns=("n","c","p","i"),show="headings")
        for a,b in [("n","Producto"),("c","Categoría"),("p","Precio"),("i","Imagen")]:t.heading(a,text=b);t.column(a,width=170)
        t.pack(fill="both",expand=True,padx=20)
        c=con()
        for n,cat,p,img in c.execute("SELECT nombre,categoria,precio,imagen FROM productos ORDER BY nombre"):t.insert("", "end",values=(n,cat,M(p),"✓" if img else "—"))
        c.close()
        tk.Button(w,text="＋ Agregar producto",command=self.addproduct,bg="#39a866",fg="white",relief="flat").pack(pady=12)

    def addproduct(self):
        w=tk.Toplevel(self);w.title("Agregar producto");w.geometry("520x500")
        tk.Label(w,text="Agregar producto",font=("Segoe UI",19,"bold")).pack(pady=15)
        tk.Label(w,text="Nombre").pack(anchor="w",padx=25);en=tk.Entry(w);en.pack(fill="x",padx=25,pady=5)
        tk.Label(w,text="Precio").pack(anchor="w",padx=25);ep=tk.Entry(w);ep.pack(fill="x",padx=25,pady=5)
        c=con();cats=[x[0] for x in c.execute("SELECT nombre FROM categorias ORDER BY id")];c.close()
        tk.Label(w,text="Categoría").pack(anchor="w",padx=25);cv=tk.StringVar(value=cats[0]);ttk.Combobox(w,textvariable=cv,values=cats,state="readonly").pack(fill="x",padx=25,pady=5)
        path=tk.StringVar();lab=tk.Label(w,text="Ninguna imagen seleccionada",wraplength=430);lab.pack(pady=5)
        def choose():
            p=filedialog.askopenfilename(filetypes=[("Imágenes","*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
            if p:path.set(p);lab.config(text="✓ "+Path(p).name)
        tk.Button(w,text="🖼 AGREGAR IMAGEN",command=choose,bg="#eef0f3",relief="flat").pack(pady=10,ipady=6)
        def save():
            n=en.get().strip()
            try:p=int(ep.get().replace(".","").replace("$","").replace(",",""))
            except:return messagebox.showerror("Error","Precio inválido.")
            if not n:return messagebox.showerror("Error","Escribe el nombre.")
            rel=copyimg(path.get(),PRODUCTS,"producto") if path.get() else ""
            c=con();c.execute("INSERT INTO productos(nombre,categoria,precio,imagen) VALUES(?,?,?,?)",(n,cv.get(),p,rel));c.commit();c.close();w.destroy();self.products()
        tk.Button(w,text="GUARDAR PRODUCTO",command=save,bg="#39a866",fg="white",relief="flat",font=("Segoe UI",11,"bold")).pack(fill="x",padx=25,pady=15,ipady=6)

    def addcat(self):
        w=tk.Toplevel(self);w.title("Nueva categoría");w.geometry("400x180");tk.Label(w,text="Nombre",font=("Segoe UI",13,"bold")).pack(pady=15);e=tk.Entry(w);e.pack(fill="x",padx=25)
        def save():
            try:
                c=con();c.execute("INSERT INTO categorias(nombre) VALUES(?)",(e.get().strip(),));c.commit();c.close();w.destroy();self.loadcats()
            except:messagebox.showwarning("Categoría","Esa categoría ya existe.")
        tk.Button(w,text="Guardar",command=save,bg="#39a866",fg="white",relief="flat").pack(pady=15)

    def settings(self):
        w=tk.Toplevel(self);w.title("Configuración");w.geometry("650x690")
        tk.Label(w,text="Imágenes de billetes y moneda",font=("Segoe UI",18,"bold")).pack(pady=15)
        for d in D:
            r=tk.Frame(w);r.pack(fill="x",padx=18,pady=4);tk.Label(r,text=M(d),width=10,font=("Segoe UI",10,"bold")).pack(side="left")
            status=tk.Label(r,text=Path(self.money[d]).name if d in self.money else "Sin imagen",anchor="w");status.pack(side="left",fill="x",expand=True)
            def choose(d=d,status=status):
                p=filedialog.askopenfilename(filetypes=[("Imágenes","*.jpg *.jpeg *.png *.gif *.bmp *.webp")])
                if p:self.money[d]=copyimg(p,MONEY,"dinero_"+str(d));status.config(text=Path(p).name);self.cashbuttons()
            tk.Button(r,text="Agregar / cambiar imagen",command=choose,relief="flat").pack(side="right")
        tk.Label(w,text="Las imágenes se copian dentro de la carpeta datos del programa.",wraplength=560).pack(pady=15)

con();App().mainloop()
