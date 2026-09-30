from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from .lan import load_lan_config, save_lan_config, BambuLanError


STEPS=[
    "1  Подготовка и Home",
    "2  Безопасная высота Z",
    "3  Рабочая / контактная Z",
    "4  Offset X/Y",
    "5  Проверка",
]


def _tool_key(value:str)->str:
    return "pen" if value=="Ручка" else "knife"


def _persist(app,key:str):
    c=getattr(app,"_lan_client",None)
    if c is None:return
    cfg=load_lan_config();store=cfg.get("tool_calibrations") if isinstance(cfg.get("tool_calibrations"),dict) else {}
    store=dict(store);per=dict(store.get(c.serial,{}) or {});per[key]=app.project.printer.get_tool_calibration(key);store[c.serial]=per
    cfg["tool_calibrations"]=store;save_lan_config(cfg)


def open_calibration_wizard(app):
    old=getattr(app,"_calibration_wizard_window",None)
    if old is not None:
        try:
            if old.winfo_exists():old.lift();return
        except Exception:pass

    client=getattr(app,"_lan_client",None)
    if client is None or not getattr(client,"connected",False):
        messagebox.showerror("Калибровка","Сначала подключите принтер в окне «Принтеры».",parent=app);return

    w=tk.Toplevel(app);app._calibration_wizard_window=w;w.title("Калибровка — Sibir Cut");w.geometry("1030x720");w.minsize(900,620);w.transient(app)
    outer=ttk.Frame(w,padding=16);outer.pack(fill="both",expand=True)

    head=ttk.Frame(outer);head.pack(fill="x")
    ttk.Label(head,text="Калибровка инструмента",style="Hero.TLabel").pack(side="left")
    tool=tk.StringVar(value="Ручка" if app.project.material.mode=="Рисование" else "Нож")
    ttk.Label(head,text="Инструмент:").pack(side="right",padx=(8,4))
    tool_cb=ttk.Combobox(head,textvariable=tool,values=["Нож","Ручка"],state="readonly",width=12);tool_cb.pack(side="right")
    ttk.Label(outer,text="Калибровка выполняется один раз для каждого инструмента и выбранного A1. Потом Sibir Cut применяет её автоматически.",style="Muted.TLabel").pack(anchor="w",pady=(2,12))

    main=ttk.Frame(outer);main.pack(fill="both",expand=True)
    nav=ttk.Frame(main,width=220);nav.pack(side="left",fill="y",padx=(0,14));nav.pack_propagate(False)
    page=ttk.Frame(main);page.pack(side="left",fill="both",expand=True)
    footer=ttk.Frame(outer);footer.pack(fill="x",pady=(12,0))
    back_btn=ttk.Button(footer,text="← Назад");back_btn.pack(side="left")
    next_btn=ttk.Button(footer,text="Далее →");next_btn.pack(side="right")
    close_btn=ttk.Button(footer,text="Закрыть");close_btn.pack(side="right",padx=8)

    step={"i":0};homed={"ok":False};reference={"x":None,"y":None}
    ref_x=tk.DoubleVar(value=float(load_lan_config().get("offset_ref_x",128.0)));ref_y=tk.DoubleVar(value=float(load_lan_config().get("offset_ref_y",128.0)))
    test_x=tk.DoubleVar(value=float(load_lan_config().get("test_x",220.0)));test_y=tk.DoubleVar(value=float(load_lan_config().get("test_y",30.0)))
    z_step=tk.DoubleVar(value=0.10);xy_step=tk.DoubleVar(value=0.20)
    safe_candidate={"z":None};work_candidate={"z":None}
    step_buttons=[]

    def key():return _tool_key(tool.get())
    def cal():return app.project.printer.get_tool_calibration(key())
    def require_client():
        c=getattr(app,"_lan_client",None)
        if c is None or not c.connected:raise BambuLanError("Принтер не подключен")
        st=c.status_summary()
        state=str(st.get("gcode_state") or "").upper()
        if state in ("RUNNING","PRINTING","PAUSE","PAUSED"):raise BambuLanError("Калибровка недоступна во время печати")
        return c
    def clear_page():
        for ch in page.winfo_children():ch.destroy()
    def title(text,sub=""):
        ttk.Label(page,text=text,style="Step.TLabel").pack(anchor="w")
        if sub:ttk.Label(page,text=sub,style="Muted.TLabel",wraplength=700).pack(anchor="w",pady=(4,16))
    def card(text):
        box=ttk.LabelFrame(page,text=text,padding=14);box.pack(fill="x",pady=(0,12));return box
    def status_text():
        cur=cal()
        return f"Сейчас: Offset X={cur['offset_x']:.3f}, Y={cur['offset_y']:.3f} мм • Z={cur['z']:.3f} • Safe Z={cur['safe_z']:.3f} • XY {'✓' if cur.get('xy_calibrated') else '—'} • Z {'✓' if cur.get('z_calibrated') else '—'}"

    def move_z(delta):
        try:
            c=require_client();ps=c.position_snapshot();z=ps.get("z")
            if z is None:raise BambuLanError("Сначала выполните переход в тестовую точку.")
            target=max(app.project.printer.min_z,min(app.project.printer.max_z,float(z)+float(delta)))
            c.move_absolute(z=target,feed=240)
            if step["i"]==1:safe_candidate["z"]=target
            else:work_candidate["z"]=target
            render()
        except Exception as exc:messagebox.showerror("Калибровка",str(exc),parent=w)

    def save_safe():
        z=safe_candidate["z"]
        if z is None:return
        cur=cal();app.project.printer.set_tool_calibration(key(),safe_z=float(z),xy_calibrated=cur.get("xy_calibrated"),z_calibrated=cur.get("z_calibrated"))
        _persist(app,key());app.apply_active_tool_calibration();app.refresh_all();render()

    def save_work():
        z=work_candidate["z"]
        if z is None:return
        cur=cal();app.project.printer.set_tool_calibration(key(),z=float(z),safe_z=max(float(cur["safe_z"]),float(z)+0.5),z_calibrated=True,xy_calibrated=cur.get("xy_calibrated"))
        _persist(app,key());app.apply_active_tool_calibration()
        if key()=="pen":app.project.material.work_z=float(z)
        else:app.project.material.work_z=float(z)
        app.refresh_all();render()

    def home():
        try:
            c=require_client()
            if not messagebox.askyesno("Home","UMTS/держатель инструмента СНЯТ с головы?\n\nHome нельзя выполнять с установленным модулем.",parent=w):return
            method=c.go_home(printing=False);homed["ok"]=True
            messagebox.showinfo("Home",f"Команда Home отправлена ({method}). Дождитесь полной остановки принтера, затем поставьте сопло в опорную точку.",parent=w)
        except Exception as exc:messagebox.showerror("Home",str(exc),parent=w)

    def set_reference():
        try:
            c=require_client()
            if not homed["ok"]:
                if not messagebox.askyesno("Калибровка","Home в этой сессии не отмечен как выполненный. Продолжить только если Home уже действительно завершён?",parent=w):return
            rx=float(ref_x.get());ry=float(ref_y.get());z=max(10.0,float(cal()["safe_z"]))
            c.move_absolute(x=rx,y=ry,z=z,feed=1500);reference["x"]=rx;reference["y"]=ry
            cfg=load_lan_config();cfg["offset_ref_x"]=rx;cfg["offset_ref_y"]=ry;save_lan_config(cfg)
            messagebox.showinfo("Опорная точка","Сопло в опорной точке. Сделайте метку точно под соплом на бумаге/малярной ленте. После этого установите UMTS с выбранным инструментом.",parent=w)
        except Exception as exc:messagebox.showerror("Калибровка",str(exc),parent=w)

    def go_safe_test():
        try:
            c=require_client();z=max(10.0,float(cal()["safe_z"]))
            c.move_absolute(x=float(test_x.get()),y=float(test_y.get()),z=z,feed=1200);safe_candidate["z"]=z;render()
        except Exception as exc:messagebox.showerror("Калибровка",str(exc),parent=w)

    def start_work():
        try:
            c=require_client();z=safe_candidate["z"]
            if z is None:z=max(10.0,float(cal()["safe_z"]))
            c.move_absolute(x=float(test_x.get()),y=float(test_y.get()),z=float(z),feed=800);work_candidate["z"]=float(z);render()
        except Exception as exc:messagebox.showerror("Калибровка",str(exc),parent=w)

    def go_offset_start():
        try:
            c=require_client()
            if reference["x"] is None:
                reference["x"]=float(ref_x.get());reference["y"]=float(ref_y.get())
            cur=cal();safe=max(float(cur["safe_z"]),float(cur["z"])+1.0,5.0)
            # Start with nozzle at the original mark. User then jogs until the
            # tool tip, not the nozzle, reaches that same physical mark.
            c.move_absolute(x=float(reference["x"]),y=float(reference["y"]),z=safe,feed=900)
            render()
        except Exception as exc:messagebox.showerror("Offset",str(exc),parent=w)

    def jog_xy(axis,sign):
        try:
            c=require_client();ps=c.position_snapshot();v=ps.get(axis.lower())
            if v is None:raise BambuLanError("Сначала нажмите «Перейти к метке».")
            target=float(v)+float(sign)*abs(float(xy_step.get()))
            if axis=="X":c.move_absolute(x=target,feed=250)
            else:c.move_absolute(y=target,feed=250)
            render()
        except Exception as exc:messagebox.showerror("Offset",str(exc),parent=w)

    def save_offset():
        try:
            c=require_client();ps=c.position_snapshot()
            if reference["x"] is None:
                reference["x"]=float(ref_x.get());reference["y"]=float(ref_y.get())
            if ps.get("x") is None or ps.get("y") is None:raise BambuLanError("Положение X/Y неизвестно.")
            ox=float(reference["x"])-float(ps["x"]);oy=float(reference["y"])-float(ps["y"])
            if abs(ox)>80 or abs(oy)>80:raise BambuLanError(f"Offset слишком большой: X={ox:.2f}, Y={oy:.2f}. Проверьте совмещение.")
            cur=cal();app.project.printer.set_tool_calibration(key(),offset_x=ox,offset_y=oy,xy_calibrated=True,z_calibrated=cur.get("z_calibrated"))
            _persist(app,key());app.apply_active_tool_calibration();app.refresh_all()
            messagebox.showinfo("Offset",f"Сохранено для {tool.get()}:\nOffset X={ox:.3f} мм\nOffset Y={oy:.3f} мм",parent=w);render()
        except Exception as exc:messagebox.showerror("Offset",str(exc),parent=w)

    def render():
        clear_page()
        for i,b in enumerate(step_buttons):
            b.config(style="Accent.TButton" if i==step["i"] else "TButton")
        i=step["i"];cur=cal()
        if i==0:
            title("Подготовка и Home","Сначала задаём общую физическую опорную точку сопла. Это нужно, чтобы Sibir Cut сам вычислил положение ножа/ручки относительно сопла.")
            b=card("1. Home без UMTS")
            ttk.Label(b,text="Снимите UMTS/держатель с головы. Нажмите Home и дождитесь полной остановки.").pack(anchor="w")
            ttk.Button(b,text="Выполнить Home",command=home).pack(anchor="w",pady=(8,0))
            b=card("2. Опорная метка сопла")
            row=ttk.Frame(b);row.pack(anchor="w")
            ttk.Label(row,text="X").pack(side="left");ttk.Entry(row,textvariable=ref_x,width=9).pack(side="left",padx=(4,12));ttk.Label(row,text="Y").pack(side="left");ttk.Entry(row,textvariable=ref_y,width=9).pack(side="left",padx=4)
            ttk.Button(b,text="Поставить сопло в опорную точку",command=set_reference).pack(anchor="w",pady=(8,0))
            ttk.Label(b,text="После остановки поставьте физическую метку под соплом. Затем установите UMTS. Эту метку используем позже для Offset X/Y.",style="Muted.TLabel",wraplength=680).pack(anchor="w",pady=(8,0))
        elif i==1:
            title("Безопасная высота Z","Сначала настраиваем высоту, на которой нож/ручка гарантированно не касается материала.")
            b=card("Тестовая точка")
            row=ttk.Frame(b);row.pack(anchor="w")
            ttk.Label(row,text="X").pack(side="left");ttk.Entry(row,textvariable=test_x,width=9).pack(side="left",padx=(4,12));ttk.Label(row,text="Y").pack(side="left");ttk.Entry(row,textvariable=test_y,width=9).pack(side="left",padx=4)
            ttk.Button(b,text="Перейти в тестовую точку на безопасной высоте",command=go_safe_test).pack(anchor="w",pady=(8,0))
            b=card("Регулировка Z")
            ttk.Label(b,text=f"Текущая Z: {safe_candidate['z'] if safe_candidate['z'] is not None else '—'}").pack(anchor="w")
            row=ttk.Frame(b);row.pack(fill="x",pady=8)
            for val in (-1.0,-0.2,-0.05,0.05,0.2,1.0):ttk.Button(row,text=f"{val:+g}",command=lambda v=val:move_z(v)).pack(side="left",padx=2)
            ttk.Button(b,text="Сохранить эту Z как безопасную",style="Accent.TButton",command=save_safe).pack(anchor="w")
        elif i==2:
            what="первое касание ручки без нажима" if key()=="pen" else "рабочую глубину ножа"
            title("Рабочая / контактная Z",f"Теперь из безопасной высоты маленькими шагами найдите {what}.")
            b=card("Точная регулировка")
            ttk.Button(b,text="Начать с безопасной Z",command=start_work).pack(anchor="w")
            ttk.Label(b,text=f"Текущая тестовая Z: {work_candidate['z'] if work_candidate['z'] is not None else '—'}").pack(anchor="w",pady=(8,0))
            row=ttk.Frame(b);row.pack(fill="x",pady=8)
            for val in (-0.5,-0.2,-0.1,-0.05,-0.02,0.02,0.05,0.1,0.2,0.5):ttk.Button(row,text=f"{val:+g}",command=lambda v=val:move_z(v)).pack(side="left",padx=2)
            ttk.Button(b,text=("Сохранить первое касание" if key()=="pen" else "Сохранить рабочую Z ножа"),style="Accent.TButton",command=save_work).pack(anchor="w")
            if key()=="pen":ttk.Label(b,text="Прижим ручки ниже этой Z остаётся параметром задания в «Настройках».",style="Muted.TLabel").pack(anchor="w",pady=(8,0))
        elif i==3:
            title("Offset X/Y","Совместите кончик инструмента с той самой меткой, которую сделали под соплом на первом шаге. Знак Offset вычислит программа.")
            b=card("Совмещение с меткой")
            ttk.Button(b,text="Перейти к метке на безопасной Z",command=go_offset_start).pack(anchor="w")
            row=ttk.Frame(b);row.pack(fill="x",pady=10)
            ttk.Label(row,text="Шаг XY").pack(side="left");ttk.Combobox(row,textvariable=xy_step,values=[1.0,0.5,0.2,0.1,0.05],state="readonly",width=8).pack(side="left",padx=6)
            for txt,ax,sgn in [("X −","X",-1),("X +","X",1),("Y −","Y",-1),("Y +","Y",1)]:ttk.Button(row,text=txt,command=lambda a=ax,s=sgn:jog_xy(a,s)).pack(side="left",padx=2)
            ps=client.position_snapshot();ttk.Label(b,text=f"Положение сопла: X={ps.get('x') if ps.get('x') is not None else '—'}  Y={ps.get('y') if ps.get('y') is not None else '—'}").pack(anchor="w")
            ttk.Button(b,text="КОНЧИК НА МЕТКЕ — сохранить Offset X/Y",style="Accent.TButton",command=save_offset).pack(anchor="w",pady=(10,0))
        else:
            title("Проверка калибровки","Эти значения будут автоматически применяться при каждом задании выбранного типа.")
            b=card(tool.get())
            ttk.Label(b,text=status_text(),font=("Segoe UI",11,"bold"),wraplength=680).pack(anchor="w")
            ready=cur.get("calibrated")
            ttk.Label(b,text="✓ Калибровка полностью готова" if ready else "Нужно завершить XY и Z",foreground="#15803d" if ready else "#b91c1c").pack(anchor="w",pady=(8,0))
            ttk.Label(b,text="Чтобы изменить любой параметр позже, снова откройте «Калибровка» и перейдите на нужный шаг.",style="Muted.TLabel",wraplength=680).pack(anchor="w",pady=(8,0))
        back_btn.config(state="normal" if i>0 else "disabled");next_btn.config(text="Готово" if i==len(STEPS)-1 else "Далее →")

    def goto(i):
        step["i"]=max(0,min(len(STEPS)-1,int(i)));render()
    for i,label in enumerate(STEPS):
        b=ttk.Button(nav,text=label,command=lambda n=i:goto(n));b.pack(fill="x",pady=3);step_buttons.append(b)

    def next_step():
        if step["i"]>=len(STEPS)-1:w.destroy();return
        goto(step["i"]+1)
    def back():goto(step["i"]-1)
    def tool_changed(event=None):
        safe_candidate["z"]=None;work_candidate["z"]=None;render()

    back_btn.config(command=back);next_btn.config(command=next_step);close_btn.config(command=w.destroy);tool_cb.bind("<<ComboboxSelected>>",tool_changed)
    def closed():app._calibration_wizard_window=None;w.destroy()
    w.protocol("WM_DELETE_WINDOW",closed);close_btn.config(command=closed)
    render()
