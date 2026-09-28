from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from .models import DEFAULT_MATERIALS, MaterialProfile


def open_job_settings(app):
    old=getattr(app,"_job_settings_window",None)
    if old is not None:
        try:
            if old.winfo_exists():old.lift();return
        except Exception:pass

    w=tk.Toplevel(app);app._job_settings_window=w;w.title("Настройки задания — Sibir Cut");w.geometry("560x760");w.minsize(500,620);w.transient(app)
    outer=ttk.Frame(w,padding=16);outer.pack(fill="both",expand=True)
    canvas=tk.Canvas(outer,highlightthickness=0,borderwidth=0)
    scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
    body=ttk.Frame(canvas);win=canvas.create_window((0,0),window=body,anchor="nw")
    canvas.configure(yscrollcommand=scroll.set);canvas.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
    body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",lambda e:canvas.itemconfigure(win,width=e.width))
    w.bind("<MouseWheel>",lambda e:canvas.yview_scroll(-max(1,abs(int(e.delta))//120) if e.delta>0 else max(1,abs(int(e.delta))//120),"units"))

    ttk.Label(body,text="Настройки задания",style="Hero.TLabel").pack(anchor="w")
    ttk.Label(body,text="Основной экран оставлен простым. Здесь находятся материал, скорости, проходы, штриховка и параметры ручки/ножа.",style="Muted.TLabel",wraplength=480).pack(anchor="w",pady=(2,12))

    mat=ttk.LabelFrame(body,text="Материал / профиль",padding=10);mat.pack(fill="x",pady=(0,10))
    cb=ttk.Combobox(mat,textvariable=app.material_var,values=[m.name for m in DEFAULT_MATERIALS],state="readonly")
    cb.pack(fill="x")
    def material_changed(event=None):
        name=app.material_var.get();m=next((x for x in DEFAULT_MATERIALS if x.name==name),None)
        if m:
            mode=app.mode.get()
            app.project.material=MaterialProfile.from_dict(m.to_dict())
            # Explicit main-screen mode wins over the preset's default mode.
            app.project.material.mode=mode
            app.refresh_all()
    cb.bind("<<ComboboxSelected>>",material_changed)

    base=ttk.LabelFrame(body,text="Общие параметры",padding=10);base.pack(fill="x",pady=(0,10))
    fields=[
        ("Проходов",app.passes),("Рабочая скорость, мм/с",app.work_speed),("Холостой ход, мм/с",app.travel_speed),
        ("Рабочая / контактная Z",app.work_z),("Безопасная Z",app.safe_z),
        ("Blade offset, мм",app.blade_offset),("Overcut, мм",app.overcut),
    ]
    for lab,var in fields:
        row=ttk.Frame(base);row.pack(fill="x",pady=3);ttk.Label(row,text=lab).pack(side="left");ttk.Entry(row,textvariable=var,width=16).pack(side="right")

    draw=ttk.LabelFrame(body,text="Рисование / штриховка",padding=10);draw.pack(fill="x",pady=(0,10))
    ttk.Label(draw,text="Что рисовать").pack(anchor="w")
    ttk.Combobox(draw,textvariable=app.drawing_style,values=["Контур + заливка","Только заливка","Только контур"],state="readonly").pack(fill="x",pady=(2,6))
    for lab,var in [
        ("Шаг штриховки, мм",app.fill_spacing),("Угол штриховки, °",app.fill_angle),
        ("Отступ штриховки от края, мм",app.fill_inset),
        ("Прижим ручки ниже Z касания, мм",app.pen_press),("Подъём ручки над Z касания, мм",app.pen_lift),
    ]:
        row=ttk.Frame(draw);row.pack(fill="x",pady=3);ttk.Label(row,text=lab).pack(side="left");ttk.Entry(row,textvariable=var,width=16).pack(side="right")
    ttk.Checkbutton(draw,text="Перекрёстная штриховка (+90°)",variable=app.fill_crosshatch).pack(anchor="w",pady=(6,0))

    ttk.Label(body,text="Z из калибровки применяется автоматически. Изменение Z здесь оставлено для осознанной ручной корректировки текущего задания.",style="Muted.TLabel",wraplength=480).pack(anchor="w",pady=(2,12))
    bar=ttk.Frame(body);bar.pack(fill="x",pady=(4,12))
    def apply():
        try:
            app.apply_job_settings()
            if hasattr(app,"update_main_summary"):app.update_main_summary()
        except Exception as exc:messagebox.showerror("Настройки",str(exc),parent=w)
    ttk.Button(bar,text="Применить",style="Accent.TButton",command=apply).pack(side="right")
    ttk.Button(bar,text="Закрыть",command=w.destroy).pack(side="right",padx=6)

    def closed():app._job_settings_window=None;w.destroy()
    w.protocol("WM_DELETE_WINDOW",closed)
