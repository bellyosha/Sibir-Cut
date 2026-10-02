from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any

from .lan import BambuLanClient, BambuLanError, load_lan_config, save_lan_config, check_lan_services
from .discovery import BambuLanScanner, discovery_identity_hint


def _saved_printers(cfg: dict[str, Any]) -> list[dict[str, str]]:
    raw=cfg.get("printers")
    out=[]
    if isinstance(raw,list):
        for item in raw:
            if not isinstance(item,dict):
                continue
            host=str(item.get("host") or item.get("ip") or "").strip()
            serial=str(item.get("serial") or "").strip()
            if not host and not serial:
                continue
            out.append({
                "host":host,
                "serial":serial,
                "name":str(item.get("name") or "").strip(),
                "model":str(item.get("model") or "").strip(),
            })
    if not out:
        host=str(cfg.get("host") or "").strip()
        serial=str(cfg.get("serial") or "").strip()
        if host or serial:
            out.append({"host":host,"serial":serial,"name":"","model":"Bambu Lab A1"})
    # Deduplicate by serial first, then host.
    seen=set();clean=[]
    for item in out:
        key=(item["serial"] or item["host"]).upper()
        if not key or key in seen:
            continue
        seen.add(key);clean.append(item)
    return clean


def _active_record(cfg: dict[str, Any]) -> dict[str, str] | None:
    items=_saved_printers(cfg)
    if not items:
        return None
    active=str(cfg.get("active_serial") or cfg.get("serial") or "").strip().upper()
    if active:
        for item in items:
            if item["serial"].upper()==active:
                return item
    active_host=str(cfg.get("host") or "").strip()
    if active_host:
        for item in items:
            if item["host"]==active_host:
                return item
    return items[0]


def _access_for(cfg: dict[str, Any], serial: str) -> str:
    codes=cfg.get("access_codes")
    if isinstance(codes,dict) and serial and codes.get(serial):
        return str(codes.get(serial) or "").strip()
    return str(cfg.get("access_code") or "").strip()


def _load_tool_calibrations(app, cfg: dict[str, Any], serial: str) -> None:
    store=cfg.get("tool_calibrations")
    if not isinstance(store,dict) or not serial:
        return
    per=store.get(serial)
    if not isinstance(per,dict):
        return
    changed=False
    for key in ("knife","pen"):
        raw=per.get(key)
        if isinstance(raw,dict):
            app.project.printer.tool_calibrations[key]=dict(raw);changed=True
    if changed:
        app.apply_active_tool_calibration()
        try:app.after(0,app.refresh_all)
        except Exception:pass


def _status(app,text,kind="idle"):
    try:
        app.after(0,lambda:app.set_printer_status(text,kind))
    except Exception:
        pass


def _save_printer_record(cfg: dict[str, Any], record: dict[str,str], access_code: str="", remember: bool=True) -> dict[str,Any]:
    data=dict(cfg or {})
    items=_saved_printers(data)
    key=(record.get("serial") or record.get("host") or "").upper()
    replaced=False
    for i,item in enumerate(items):
        ikey=(item.get("serial") or item.get("host") or "").upper()
        if key and ikey==key:
            items[i]=dict(record);replaced=True;break
    if not replaced:
        items.append(dict(record))
    data["printers"]=items
    data["active_serial"]=record.get("serial","")
    data["host"]=record.get("host","")
    data["serial"]=record.get("serial","")
    data["remember_access_code"]=bool(remember)
    codes=data.get("access_codes") if isinstance(data.get("access_codes"),dict) else {}
    codes=dict(codes)
    if remember and record.get("serial") and access_code:
        codes[record["serial"]]=access_code
        data["access_code"]=access_code
    data["access_codes"]=codes
    save_lan_config(data)
    return data


def connect_printer(app, record: dict[str,str], access_code: str, *, remember: bool=True, quiet: bool=False) -> bool:
    app._lan_connection_error=""
    record=dict(record)
    host=str(record.get("host") or "").strip();serial=str(record.get("serial") or "").strip();code=str(access_code or "").strip()
    if not host or not code:
        app._lan_connection_error="Нужны IP и LAN access code. Serial можно ввести вручную или оставить пустым для автоопределения."
        if not quiet:
            messagebox.showerror("Принтер",app._lan_connection_error,parent=app)
        return False
    old=getattr(app,"_lan_client",None)
    if old is not None:
        try:
            if old.connected and old.host==host and old.serial==serial and old.access_code==code:
                _status(app,f"{record.get('name') or 'Bambu A1'} • {host} • подключен","ok")
                return True
        except Exception:
            pass
        try:old.close()
        except Exception:pass
        app._lan_client=None

    try:
        client=BambuLanClient(host,code,serial,on_update=lambda:_refresh_connection_status(app))
        client.connect(timeout=6.0)
        record["serial"]=serial=client.serial
        app._lan_client=client
        cfg=load_lan_config()
        cfg=_save_printer_record(cfg,record,code,remember)
        _load_tool_calibrations(app,cfg,serial)
        _status(app,f"{record.get('name') or 'Bambu A1'} • {host} • подключен","ok")
        return True
    except Exception as exc:
        app._lan_connection_error=str(exc)
        app._lan_client=None
        if 'client' in locals():
            try:client.close()
            except Exception:pass
        _status(app,f"{record.get('name') or 'Bambu A1'} • нет связи","bad")
        if not quiet:
            messagebox.showerror("Подключение к принтеру",str(exc),parent=app)
        return False


def _refresh_connection_status(app):
    c=getattr(app,"_lan_client",None)
    if c is None:
        _status(app,"Принтер не подключен","idle");return
    try:
        if c.connected:
            st=c.status_summary();state=st.get("gcode_state") or "—"
            _status(app,f"Bambu A1 • {c.host} • {state}","ok")
        else:
            _status(app,f"Bambu A1 • {c.host} • нет связи","bad")
    except Exception:
        _status(app,"Принтер не подключен","bad")


def auto_connect_saved_printer(app):
    """Connect the selected saved printer once at app start, without blocking UI."""
    if getattr(app,"_auto_connect_started",False):
        return
    app._auto_connect_started=True
    cfg=load_lan_config();rec=_active_record(cfg)
    if not rec:
        _status(app,"Принтер не настроен","idle");return
    code=_access_for(cfg,rec.get("serial",""))
    if not code:
        _status(app,f"{rec.get('name') or 'Bambu A1'} • нужен access code","warn");return
    _status(app,f"{rec.get('name') or 'Bambu A1'} • подключение…","warn")
    def worker():
        connect_printer(app,rec,code,remember=True,quiet=True)
    threading.Thread(target=worker,daemon=True).start()


def open_printer_manager(app):
    old=getattr(app,"_printer_manager_window",None)
    if old is not None:
        try:
            if old.winfo_exists():old.lift();return
        except Exception:pass

    cfg=load_lan_config()
    w=tk.Toplevel(app);app._printer_manager_window=w;w.title("Принтеры — Sibir Cut");w.geometry("980x720");w.minsize(820,600);w.transient(app)
    root=ttk.Frame(w,padding=16);root.pack(fill="both",expand=True)
    ttk.Label(root,text="Принтеры",style="Hero.TLabel").pack(anchor="w")
    ttk.Label(root,text="Один раз сохраните A1 — при следующих запусках Sibir Cut подключится к выбранному принтеру автоматически.",style="Muted.TLabel").pack(anchor="w",pady=(2,12))

    saved_box=ttk.LabelFrame(root,text="Мои принтеры",padding=10);saved_box.pack(fill="x")
    cols=("name","model","ip","serial","status")
    saved=ttk.Treeview(saved_box,columns=cols,show="headings",height=5,selectmode="browse")
    for key,title,width in [("name","Имя",150),("model","Модель",130),("ip","IP",120),("serial","Серийный номер",190),("status","Состояние",160)]:
        saved.heading(key,text=title);saved.column(key,width=width,anchor="w",stretch=(key in ("name","status")))
    saved.pack(fill="x")

    edit=ttk.Frame(saved_box);edit.pack(fill="x",pady=(8,0))
    host=tk.StringVar();serial=tk.StringVar();name=tk.StringVar(value="Bambu A1");access=tk.StringVar();remember=tk.BooleanVar(value=True)
    for lab,var,wid in [("Имя",name,16),("IP",host,14),("Serial",serial,20),("Access code",access,14)]:
        ttk.Label(edit,text=lab).pack(side="left",padx=(0,4));ttk.Entry(edit,textvariable=var,width=wid,show="*" if lab=="Access code" else "").pack(side="left",padx=(0,10))
    ttk.Checkbutton(saved_box,text="Запомнить access code на этом компьютере",variable=remember).pack(anchor="w",pady=(6,0))
    ttk.Label(saved_box,text="Serial можно оставить пустым для автоопределения по MQTT. Нужен SN самого принтера, не AMS.",style="Muted.TLabel").pack(anchor="w",pady=(3,0))
    actions=ttk.Frame(saved_box);actions.pack(fill="x",pady=(8,0))
    connect_btn=ttk.Button(actions,text="Подключить / сделать активным");connect_btn.pack(side="left")
    disconnect_btn=ttk.Button(actions,text="Отключить");disconnect_btn.pack(side="left",padx=6)
    diagnose_btn=ttk.Button(actions,text="Проверить LAN");diagnose_btn.pack(side="left",padx=(0,6))
    remove_btn=ttk.Button(actions,text="Удалить из списка");remove_btn.pack(side="left")
    advanced_btn=ttk.Button(actions,text="Расширенное LAN управление");advanced_btn.pack(side="right")

    scan_box=ttk.LabelFrame(root,text="Поиск Bambu в локальной сети",padding=10);scan_box.pack(fill="both",expand=True,pady=(14,0))
    scanbar=ttk.Frame(scan_box);scanbar.pack(fill="x")
    scan_btn=ttk.Button(scanbar,text="Сканировать сеть");scan_btn.pack(side="left")
    scan_status=tk.StringVar(value="Поиск не запускался");ttk.Label(scanbar,textvariable=scan_status).pack(side="left",padx=10)
    dcols=("name","model","ip","serial","signal")
    found_tree=ttk.Treeview(scan_box,columns=dcols,show="headings",height=8,selectmode="browse")
    for key,title,width in [("name","Имя",160),("model","Модель",160),("ip","IP",120),("serial","Серийный номер",200),("signal","Сигнал",80)]:
        found_tree.heading(key,text=title);found_tree.column(key,width=width,anchor="w",stretch=(key in ("name","model","serial")))
    found_tree.pack(fill="both",expand=True,pady=(8,0))
    use_btn=ttk.Button(scan_box,text="Добавить выбранный принтер");use_btn.pack(anchor="e",pady=(8,0))

    scanner={"obj":None,"running":False};found={}

    def current_connected_key():
        c=getattr(app,"_lan_client",None)
        if c is not None:
            try:
                if c.connected:return (c.serial or c.host).upper()
            except Exception:pass
        return ""

    def refresh_saved():
        nonlocal cfg
        cfg=load_lan_config();saved.delete(*saved.get_children());active=str(cfg.get("active_serial") or "").upper();conn=current_connected_key()
        for idx,item in enumerate(_saved_printers(cfg)):
            key=(item.get("serial") or item.get("host") or f"p{idx}").upper()
            if key==conn:status="● Подключен"
            elif item.get("serial","").upper()==active:status="Активный • нет связи"
            else:status="Сохранён"
            saved.insert("","end",iid=f"s{idx}",values=(item.get("name") or "Bambu A1",item.get("model") or "Bambu Lab A1",item.get("host"),item.get("serial"),status))

    def selected_saved():
        sel=saved.selection()
        if not sel:return None
        vals=saved.item(sel[0],"values")
        return {"name":str(vals[0]),"model":str(vals[1]),"host":str(vals[2]),"serial":str(vals[3])}

    def load_saved_fields(event=None):
        item=selected_saved()
        if not item:return
        name.set(item["name"]);host.set(item["host"]);serial.set(item["serial"]);access.set(_access_for(load_lan_config(),item["serial"]))

    def do_connect():
        rec={"name":name.get().strip() or "Bambu A1","model":"Bambu Lab A1","host":host.get().strip(),"serial":serial.get().strip()}
        code=access.get().strip()
        remember_value=bool(remember.get())
        connect_btn.config(state="disabled")
        def worker():
            ok=connect_printer(app,rec,code,remember=remember_value,quiet=True)
            def done():
                if not w.winfo_exists():return
                connect_btn.config(state="normal");refresh_saved()
                if ok:
                    c=getattr(app,"_lan_client",None)
                    if c is not None:
                        host.set(c.host);serial.set(c.serial)
                else:messagebox.showerror("Подключение",getattr(app,"_lan_connection_error","") or "Не удалось подключиться. Используйте «Проверить LAN».",parent=w)
            app.after(0,done)
        threading.Thread(target=worker,daemon=True).start()

    def diagnose():
        target=host.get().strip();diagnose_btn.config(state="disabled")
        def worker():
            try:result=check_lan_services(target)
            except Exception as exc:result=str(exc)
            def done():
                if not w.winfo_exists():return
                diagnose_btn.config(state="normal");messagebox.showinfo("Проверка LAN",result,parent=w)
            app.after(0,done)
        threading.Thread(target=worker,daemon=True).start()

    def do_disconnect():
        c=getattr(app,"_lan_client",None)
        if c is not None:
            try:c.close()
            except Exception:pass
        app._lan_client=None;_status(app,"Принтер отключен","idle");refresh_saved()

    def do_remove():
        nonlocal cfg
        item=selected_saved()
        if not item:return
        data=load_lan_config();items=[x for x in _saved_printers(data) if (x.get("serial") or x.get("host"))!=(item.get("serial") or item.get("host"))]
        data["printers"]=items
        if str(data.get("active_serial") or "")==item.get("serial"):data["active_serial"]=items[0].get("serial","") if items else ""
        save_lan_config(data);refresh_saved()

    def discovered_key(p):
        return str(p.serial or p.ip)
    def add_found(p):
        for old_key,old in list(found.items()):
            if old.ip==p.ip and old_key!=discovered_key(p):
                found.pop(old_key,None)
                if found_tree.exists(old_key):found_tree.delete(old_key)
        key=discovered_key(p);found[key]=p
        vals=(p.display_name(),p.model_name or p.model_code or "Выберите модель",p.ip,p.serial or "авто при подключении",p.signal or "—")
        if found_tree.exists(key):found_tree.item(key,values=vals)
        else:found_tree.insert("","end",iid=key,values=vals)
        scan_status.set(f"Принтеров: {sum(p.source=='ssdp' for p in found.values())} • кандидатов по порту: {sum(p.source=='tcp' for p in found.values())}")
    def scan_done(items):
        scanner["running"]=False;scan_btn.config(state="normal")
        scan_status.set(f"Готово • принтеров: {sum(p.source=='ssdp' for p in items)} • кандидатов: {sum(p.source=='tcp' for p in items)}")
    def do_scan():
        if scanner["running"]:return
        found.clear();found_tree.delete(*found_tree.get_children());scanner["running"]=True;scan_btn.config(state="disabled");scan_status.set("Сканирование…")
        sc=BambuLanScanner(on_printer=lambda p:app.after(0,lambda pp=p:add_found(pp)),on_done=lambda items:app.after(0,lambda ii=items:scan_done(ii)))
        scanner["obj"]=sc;threading.Thread(target=lambda:sc.scan(5.5),daemon=True).start()
    def use_found(event=None):
        sel=found_tree.selection()
        if not sel:return
        p=found.get(sel[0])
        if p is None:return
        name.set(p.name or "Bambu A1");host.set(p.ip);serial.set(p.serial or "")
        access.set(_access_for(load_lan_config(),p.serial) if p.serial else "")
        if not p.serial:messagebox.showinfo("Данные найденного адреса",discovery_identity_hint(p),parent=w)

    def open_advanced():
        from .lan_gui import open_lan_control
        open_lan_control(app)

    def closed():
        sc=scanner.get("obj")
        if sc is not None:
            try:sc.stop()
            except Exception:pass
        app._printer_manager_window=None;w.destroy()

    saved.bind("<<TreeviewSelect>>",load_saved_fields);found_tree.bind("<Double-1>",use_found)
    connect_btn.config(command=do_connect);disconnect_btn.config(command=do_disconnect);remove_btn.config(command=do_remove)
    diagnose_btn.config(command=diagnose)
    scan_btn.config(command=do_scan);use_btn.config(command=use_found);advanced_btn.config(command=open_advanced)
    w.protocol("WM_DELETE_WINDOW",closed)
    refresh_saved()
    active=_active_record(cfg)
    if active:
        name.set(active.get("name") or "Bambu A1");host.set(active.get("host") or "");serial.set(active.get("serial") or "");access.set(_access_for(cfg,active.get("serial","")))
    w.after(350,do_scan)
