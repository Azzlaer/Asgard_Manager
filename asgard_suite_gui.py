from __future__ import annotations
import tkinter as tk
from tkinter import messagebox, ttk

class AsgardSuiteWindow(tk.Toplevel):
    def __init__(self, parent, api, server_id: int):
        super().__init__(parent)
        self.api=api; self.server_id=server_id
        self.title("ASGARD Server Suite")
        self.geometry("1180x720"); self.minsize(900,600)
        self.transient(parent)
        root=ttk.Frame(self,padding=12); root.pack(fill="both",expand=True)
        settings=api.request("GET",f"/asgard-suite/{server_id}/settings")
        bar=ttk.LabelFrame(root,text="Puente seguro Host Manager ↔ Valheim",padding=10); bar.pack(fill="x")
        self.enabled=tk.BooleanVar(value=bool(settings.get("enabled")))
        self.mode=tk.StringVar(value=settings.get("mode","observe"))
        self.token=tk.StringVar(value=settings.get("api_token",""))
        ttk.Checkbutton(bar,text="Habilitado",variable=self.enabled).grid(row=0,column=0,padx=5)
        ttk.Label(bar,text="Modo").grid(row=0,column=1,padx=(20,5))
        ttk.Combobox(bar,textvariable=self.mode,state="readonly",values=["observe","manual","automatic"],width=14).grid(row=0,column=2)
        ttk.Label(bar,text="Token").grid(row=0,column=3,padx=(20,5))
        ttk.Entry(bar,textvariable=self.token,width=52,show="•").grid(row=0,column=4,sticky="ew")
        bar.columnconfigure(4,weight=1)
        ttk.Button(bar,text="Guardar",style="Accent.TButton",command=self.save).grid(row=0,column=5,padx=(8,0))
        note=("observe: solo registra; manual: prepara el castigo para aprobación; automatic: permite al mod ejecutar y banear "
              "cuando la identidad y la evidencia superan el umbral configurado.")
        ttk.Label(bar,text=note,wraplength=1080).grid(row=1,column=0,columnspan=6,sticky="w",pady=(8,0))
        tabs=ttk.Notebook(root); tabs.pack(fill="both",expand=True,pady=(10,0))
        self.audit=ttk.Treeview(tabs,columns=("date","type","sev","player","id","prefab"),show="headings")
        for c,t,w in [("date","Fecha",150),("type","Evento",180),("sev","Sev.",65),("player","Jugador",150),("id","Platform ID",210),("prefab","Objeto",230)]:
            self.audit.heading(c,text=t); self.audit.column(c,width=w)
        self.pun=ttk.Treeview(tabs,columns=("date","status","sev","player","id","mode","reason"),show="headings")
        for c,t,w in [("date","Fecha",150),("status","Estado",100),("sev","Sev.",65),("player","Jugador",140),("id","Platform ID",190),("mode","Avatar",90),("reason","Motivo",330)]:
            self.pun.heading(c,text=t); self.pun.column(c,width=w)
        tabs.add(self.audit,text="Asgard Audit"); tabs.add(self.pun,text="Castigos")
        footer=ttk.Frame(root); footer.pack(fill="x",pady=(8,0))
        ttk.Button(footer,text="Actualizar",command=self.refresh).pack(side="left")
        ttk.Button(footer,text="Cerrar",command=self.destroy).pack(side="right")
        self.refresh()
    def save(self):
        try:
            self.api.request("PUT",f"/asgard-suite/{self.server_id}/settings",{"enabled":self.enabled.get(),"mode":self.mode.get(),"api_token":self.token.get()})
            messagebox.showinfo("ASGARD","Configuración guardada",parent=self)
        except Exception as exc: messagebox.showerror("ASGARD",str(exc),parent=self)
    def refresh(self):
        try:
            for tree in (self.audit,self.pun): tree.delete(*tree.get_children())
            for r in self.api.request("GET",f"/asgard-suite/{self.server_id}/audit?limit=500"):
                self.audit.insert("","end",values=(r.get("created_at",""),r.get("event_type",""),r.get("severity",0),r.get("player_name",""),r.get("platform_id",""),r.get("prefab","")))
            for r in self.api.request("GET",f"/asgard-suite/{self.server_id}/punishments?limit=300"):
                self.pun.insert("","end",values=(r.get("created_at",""),r.get("status",""),r.get("severity",0),r.get("player_name",""),r.get("platform_id",""),r.get("avatar_mode",""),r.get("reason","")))
        except Exception as exc: messagebox.showerror("ASGARD",str(exc),parent=self)
