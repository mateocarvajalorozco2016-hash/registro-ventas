import tkinter as tk
from tkinter import messagebox
import sqlite3
from datetime import datetime

DB="ventas.db"

def money(n):
    return "$" + f"{n:,}".replace(",", ".")

con=sqlite3.connect(DB)
con.execute("CREATE TABLE IF NOT EXISTS ventas(id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, total INTEGER, recibido INTEGER, cambio INTEGER)")
con.execute("CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, precio INTEGER)")
con.commit()

root=tk.Tk()
root.title("Registro de Ventas")
root.geometry("900x600")
root.configure(bg="#f4f5f7")

cart=[]
total_var=tk.StringVar(value="$0")
received_var=tk.StringVar(value="$0")
change_var=tk.StringVar(value="$0")

tk.Label(root,text="REGISTRO DE VENTAS",font=("Segoe UI",24,"bold"),bg="#17191d",fg="white",pady=18).pack(fill="x")

search=tk.Entry(root,font=("Segoe UI",14))
search.pack(fill="x",padx=25,pady=20,ipady=8)

products=tk.Frame(root,bg="#f4f5f7")
products.pack(fill="x",padx=25)

def add(name,price):
    cart.append((name,price))
    refresh()

def refresh():
    total=sum(p for _,p in cart)
    total_var.set(money(total))
    received_var.set(money(received))
    change_var.set(money(max(0,received-total)))
    for w in cartbox.winfo_children(): w.destroy()
    for name,price in cart:
        tk.Label(cartbox,text=f"{name}   {money(price)}",bg="white",font=("Segoe UI",11),anchor="w").pack(fill="x",padx=8,pady=4)

def do_search(event=None):
    for w in products.winfo_children(): w.destroy()
    q=search.get().lower()
    rows=con.execute("SELECT nombre,precio FROM productos WHERE lower(nombre) LIKE ?",(f"%{q}%",)).fetchall()
    if not rows:
        tk.Button(products,text=f'No existe "{search.get()}"\n+ AGREGAR PRODUCTO',
                  command=add_product,bg="#fff0cf",font=("Segoe UI",11,"bold"),
                  relief="flat",width=24,height=3).pack(side="left",padx=5)
    else:
        for name,price in rows[:12]:
            tk.Button(products,text=f"{name}\n{money(price)}",command=lambda n=name,p=price:add(n,p),
                      bg="white",relief="flat",width=18,height=3,font=("Segoe UI",10,"bold")).pack(side="left",padx=5)

def add_product():
    win=tk.Toplevel(root); win.title("Agregar producto"); win.geometry("360x230")
    tk.Label(win,text="Nombre").pack(pady=(15,3))
    n=tk.Entry(win); n.pack(fill="x",padx=20)
    tk.Label(win,text="Precio").pack(pady=(10,3))
    p=tk.Entry(win); p.pack(fill="x",padx=20)
    def save():
        try: price=int(p.get().replace(".","").replace("$",""))
        except: messagebox.showerror("Error","Precio inválido"); return
        con.execute("INSERT INTO productos(nombre,precio) VALUES(?,?)",(n.get(),price)); con.commit()
        win.destroy(); do_search()
    tk.Button(win,text="Guardar",command=save,bg="#39a866",fg="white",relief="flat").pack(pady=15)

tk.Label(root,text="Venta actual",font=("Segoe UI",15,"bold"),bg="#f4f5f7").pack(anchor="w",padx=25,pady=(20,5))
cartbox=tk.Frame(root,bg="white")
cartbox.pack(fill="both",expand=True,padx=25)

bar=tk.Frame(root,bg="#17191d")
bar.pack(fill="x")
tk.Label(bar,text="TOTAL",bg="#17191d",fg="white",font=("Segoe UI",12)).pack(side="left",padx=15,pady=15)
tk.Label(bar,textvariable=total_var,bg="#17191d",fg="white",font=("Segoe UI",20,"bold")).pack(side="left")
tk.Label(bar,text="   RECIBIDO",bg="#17191d",fg="white",font=("Segoe UI",12)).pack(side="left")
received=0
tk.Label(bar,textvariable=received_var,bg="#17191d",fg="white",font=("Segoe UI",18,"bold")).pack(side="left")
tk.Label(bar,text="   CAMBIO",bg="#17191d",fg="white",font=("Segoe UI",12)).pack(side="left")
tk.Label(bar,textvariable=change_var,bg="#17191d",fg="white",font=("Segoe UI",18,"bold")).pack(side="left")

def receive():
    global received
    try: received=int(pay.get().replace(".","").replace("$",""))
    except: received=0
    refresh()

pay=tk.Entry(root,font=("Segoe UI",13))
pay.pack(side="left",padx=25,pady=12,ipady=6)
tk.Button(root,text="Dinero recibido",command=receive).pack(side="left")

def save_sale():
    total=sum(p for _,p in cart)
    if not cart: return
    if received<total: return messagebox.showwarning("Pago","El dinero recibido no alcanza.")
    cur=con.cursor()
    cur.execute("INSERT INTO ventas(fecha,total,recibido,cambio) VALUES(?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),total,received,received-total))
    con.commit()
    messagebox.showinfo("Venta registrada",f"Total: {money(total)}\nCambio: {money(received-total)}")
    cart.clear()
    refresh()

tk.Button(root,text="REGISTRAR VENTA",command=save_sale,bg="#39a866",fg="white",
          font=("Segoe UI",12,"bold"),relief="flat",height=2).pack(side="right",padx=25,pady=8)

search.bind("<KeyRelease>",do_search)
do_search()
root.mainloop()
