from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .lan import BambuLanClient, BambuLanError, load_lan_config, save_lan_config


def open_lan_control(app):
    old=getattr(app,'_lan_window',None)
    if old is not None:
        try:
            if old.winfo_exists():old.lift();return
        except Exception:pass
    cfg=load_lan_config();p=app.project.printer
    w=tk.Toplevel(app);app._lan_window=w;w.title('LAN управление — Bambu Lab A1');w.geometry('790x790');w.minsize(720,650);w.transient(app)
    outer=ttk.Frame(w,padding=10);outer.pack(fill='both',expand=True)

    host=tk.StringVar(value=str(cfg.get('host','')));serial=tk.StringVar(value=str(cfg.get('serial','')));access=tk.StringVar(value=str(cfg.get('access_code','')))
    remember=tk.BooleanVar(value=bool(cfg.get('remember_access_code',False)))
    l,b,r,t=p.safe_bounds
    default_tx=min(230.0,max(l+15.0,r-15.0));default_ty=min(t-10.0,max(b+10.0,25.0))
    test_x=tk.DoubleVar(value=float(cfg.get('test_x',default_tx)));test_y=tk.DoubleVar(value=float(cfg.get('test_y',default_ty)))
    step_var=tk.DoubleVar(value=float(cfg.get('z_step',0.10)));home_ok=tk.BooleanVar(value=False)
    conn_status=tk.StringVar(value='Не подключено');printer_status=tk.StringVar(value='Статус принтера: —');z_status=tk.StringVar(value='Z команды: НЕ СИНХРОНИЗИРОВАНА')
    candidate_status=tk.StringVar(value='Z теста: —')
    actual_z={'value':None};candidate_z={'value':None};connecting={'value':False};last_state={'value':'—'}

    net=ttk.LabelFrame(outer,text='Подключение к A1 по LAN',padding=10);net.pack(fill='x')
    net.columnconfigure(1,weight=1)
    for row,(lab,var,show) in enumerate([('IP принтера',host,''),('Серийный номер',serial,''),('LAN access code',access,'*')]):
        ttk.Label(net,text=lab,width=19).grid(row=row,column=0,sticky='w',pady=3)
        ttk.Entry(net,textvariable=var,show=show).grid(row=row,column=1,sticky='ew',pady=3,padx=(6,0))
    ttk.Checkbutton(net,text='Запомнить access code на этом компьютере',variable=remember).grid(row=3,column=0,columnspan=2,sticky='w',pady=(4,0))
    ttk.Label(net,text='На актуальной прошивке для сторонних LAN-команд должен быть включён Developer Mode. Home из приложения намеренно не выполняется.',foreground='#b45309',wraplength=730).grid(row=4,column=0,columnspan=2,sticky='w',pady=(6,2))
    bar=ttk.Frame(net);bar.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(8,0))
    connect_btn=ttk.Button(bar,text='Подключиться');connect_btn.pack(side='left')
    disconnect_btn=ttk.Button(bar,text='Отключиться');disconnect_btn.pack(side='left',padx=5)
    ttk.Label(bar,textvariable=conn_status).pack(side='left',padx=10)

    stat=ttk.LabelFrame(outer,text='Состояние',padding=10);stat.pack(fill='x',pady=(10,0))
    ttk.Label(stat,textvariable=printer_status,style='Title.TLabel').pack(anchor='w')
    ttk.Label(stat,textvariable=z_status,font=('Segoe UI',14,'bold')).pack(anchor='w',pady=(7,0))
    ttk.Label(stat,textvariable=candidate_status).pack(anchor='w',pady=(2,0))
    ttk.Label(stat,text='Важно: A1 не передаёт фактические координаты XYZ в LAN-статусе. Здесь показывается Z, которую отправило именно это окно. Если двигали оси с экрана принтера — синхронизацию нужно выполнить заново.',foreground='#b45309',wraplength=730).pack(anchor='w',pady=(6,0))

    calib=ttk.LabelFrame(outer,text='Калибровка ножа / ручки на маленьком тестовом участке',padding=10);calib.pack(fill='both',expand=True,pady=(10,0))
    ttk.Checkbutton(calib,text='Home уже выполнен ВРУЧНУЮ при СНЯТОМ UMTS',variable=home_ok).pack(anchor='w')
    pos=ttk.Frame(calib);pos.pack(fill='x',pady=8)
    ttk.Label(pos,text='Точка КОНЧИКА инструмента X, мм').grid(row=0,column=0,sticky='w');ttk.Entry(pos,textvariable=test_x,width=9).grid(row=0,column=1,padx=(6,16))
    ttk.Label(pos,text='Y, мм').grid(row=0,column=2,sticky='w');ttk.Entry(pos,textvariable=test_y,width=9).grid(row=0,column=3,padx=6)
    ttk.Label(pos,text='Участок используется только для ручной настройки перед работой.',foreground='#475569').grid(row=1,column=0,columnspan=4,sticky='w',pady=(4,0))
    sync_btn=ttk.Button(calib,text='1. Поднять на безопасную Z и перейти в тестовую точку');sync_btn.pack(fill='x',pady=(2,8))

    jog=ttk.LabelFrame(calib,text='Точная регулировка Z',padding=8);jog.pack(fill='x')
    jr=ttk.Frame(jog);jr.pack(fill='x')
    ttk.Label(jr,text='Шаг, мм').pack(side='left');ttk.Combobox(jr,textvariable=step_var,values=[0.01,0.02,0.05,0.10,0.20,0.50,1.00],state='readonly',width=8).pack(side='left',padx=6)
    lower_btn=ttk.Button(jr,text='Ниже / СИЛЬНЕЕ');lower_btn.pack(side='left',expand=True,fill='x',padx=4)
    raise_btn=ttk.Button(jr,text='Выше / СЛАБЕЕ');raise_btn.pack(side='left',expand=True,fill='x',padx=4)
    return_btn=ttk.Button(jog,text='Вернуться к выбранной Z теста');return_btn.pack(fill='x',pady=(7,0))

    test=ttk.LabelFrame(calib,text='Проверка на материале',padding=8);test.pack(fill='x',pady=(8,0))
    ttk.Label(test,text='Программа опустит инструмент на выбранную Z, проведёт линию 10 мм и сразу поднимет его обратно на безопасную Z.',wraplength=700).pack(anchor='w')
    line_btn=ttk.Button(test,text='Сделать тестовую линию 10 мм');line_btn.pack(fill='x',pady=(6,0))

    save=ttk.LabelFrame(calib,text='Сохранить настройку в текущее задание',padding=8);save.pack(fill='x',pady=(8,0))
    save_contact_btn=ttk.Button(save,text='Ручка: сохранить Z теста как ПЕРВОЕ касание');save_contact_btn.pack(fill='x',pady=2)
    save_press_btn=ttk.Button(save,text='Ручка: сохранить текущий прижим относительно первого касания');save_press_btn.pack(fill='x',pady=2)
    save_knife_btn=ttk.Button(save,text='Нож: сохранить Z теста как рабочую глубину');save_knife_btn.pack(fill='x',pady=2)

    def client():return getattr(app,'_lan_client',None)
    def fmt(v):
        try:return f'{float(v):.1f}'
        except Exception:return '—'
    def reset_z():
        actual_z['value']=None;z_status.set('Z команды: НЕ СИНХРОНИЗИРОВАНА')
    def set_actual_z(v):
        actual_z['value']=float(v);z_status.set(f'Z команды: {float(v):.3f} мм')
    def set_candidate(v):
        candidate_z['value']=float(v);candidate_status.set(f'Z теста: {float(v):.3f} мм')
    def save_cfg():
        data={'host':host.get().strip(),'serial':serial.get().strip(),'remember_access_code':bool(remember.get()),'test_x':float(test_x.get()),'test_y':float(test_y.get()),'z_step':float(step_var.get())}
        if remember.get():data['access_code']=access.get().strip()
        save_lan_config(data)
    def tool_point(line_len=0.0):
        tx=float(test_x.get());ty=float(test_y.get());l0,b0,r0,t0=app.project.printer.safe_bounds
        if not (l0<=tx<=r0 and b0<=ty<=t0 and l0<=tx+line_len<=r0):
            raise BambuLanError(f'Тестовый участок инструмента должен быть внутри безопасной зоны X {l0:.1f}…{r0:.1f}, Y {b0:.1f}…{t0:.1f} мм.')
        nx=tx-app.project.printer.tool_offset_x;ny=ty-app.project.printer.tool_offset_y;nx2=tx+line_len-app.project.printer.tool_offset_x
        if not (0<=nx<=app.project.printer.bed_width and 0<=nx2<=app.project.printer.bed_width and 0<=ny<=app.project.printer.bed_height):
            raise BambuLanError('С учётом Offset X/Y сопло вышло бы за физические границы стола. Измените тестовую точку.')
        return nx,ny,nx2
    def ready(require_z=False):
        c=client()
        if c is None or not c.connected:raise BambuLanError('Сначала подключитесь к принтеру')
        state=c.status_summary().get('gcode_state','—').upper()
        if state == '—':
            raise BambuLanError('Статус принтера ещё не получен. Подождите 1–2 секунды после подключения.')
        if state not in ('IDLE','FINISH','FAILED'):
            raise BambuLanError(f'Ручная калибровка заблокирована: состояние принтера {state}. Дождитесь остановки задания.')
        if not home_ok.get():raise BambuLanError('Сначала вручную выполните Home на A1 при СНЯТОМ UMTS и поставьте галочку подтверждения.')
        if require_z and actual_z['value'] is None:raise BambuLanError('Z не синхронизирована. Сначала перейдите в тестовую точку кнопкой №1.')
        return c
    def do_sync():
        try:
            c=ready();nx,ny,_=tool_point();safe=max(float(app.project.printer.safe_z),float(app.project.material.safe_z))
            if not (app.project.printer.min_z<=safe<=app.project.printer.max_z):raise BambuLanError('Безопасная Z профиля вне допустимого диапазона')
            c.send_gcode(f'M104 S0\nM140 S0\nG90\nG1 Z{safe:.3f} F600\nM400\nG1 X{nx:.3f} Y{ny:.3f} F3000\nM400')
            set_actual_z(safe);set_candidate(safe);save_cfg()
        except Exception as exc:messagebox.showerror('LAN калибровка',str(exc),parent=w)
    def jog_z(delta):
        try:
            c=ready(require_z=True);nz=float(actual_z['value'])+float(delta)
            if not (app.project.printer.min_z<=nz<=app.project.printer.max_z):raise BambuLanError(f'Z {nz:.3f} мм вне диапазона профиля')
            c.send_gcode(f'G90\nG1 Z{nz:.3f} F120\nM400');set_actual_z(nz);set_candidate(nz);save_cfg()
        except Exception as exc:messagebox.showerror('LAN калибровка',str(exc),parent=w)
    def back_to_candidate():
        try:
            c=ready();z=candidate_z['value']
            if z is None:raise BambuLanError('Сначала выберите Z теста кнопками выше/ниже')
            c.send_gcode(f'G90\nG1 Z{float(z):.3f} F120\nM400');set_actual_z(z)
        except Exception as exc:messagebox.showerror('LAN калибровка',str(exc),parent=w)
    def test_line():
        try:
            c=ready();z=candidate_z['value']
            if z is None:raise BambuLanError('Сначала выберите Z теста')
            nx,ny,nx2=tool_point(10.0);safe=max(float(app.project.printer.safe_z),float(app.project.material.safe_z),float(z)+1.0)
            safe=min(safe,app.project.printer.max_z)
            g=f'G90\nG1 Z{safe:.3f} F600\nM400\nG1 X{nx:.3f} Y{ny:.3f} F2400\nM400\nG1 Z{float(z):.3f} F120\nM400\nG1 X{nx2:.3f} Y{ny:.3f} F300\nM400\nG1 Z{safe:.3f} F600\nM400'
            c.send_gcode(g);set_actual_z(safe);save_cfg()
        except Exception as exc:messagebox.showerror('Тестовая линия',str(exc),parent=w)
    def save_contact():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            app.checkpoint();app.project.printer.work_z=float(z);app.project.material.work_z=float(z);app.refresh_all()
            messagebox.showinfo('Калибровка ручки',f'Первое касание сохранено: Z={float(z):.3f} мм. Теперь можно опустить ручку ещё на 0,05–0,10 мм и сохранить прижим.',parent=w)
        except Exception as exc:messagebox.showerror('Калибровка ручки',str(exc),parent=w)
    def save_press():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            contact=float(app.project.printer.work_z);press=contact-float(z)
            if not (0.0<=press<=0.5):raise BambuLanError(f'Получился прижим {press:.3f} мм. Допустимый диапазон для ручки 0…0,5 мм.')
            app.checkpoint();app.project.material.drawing_press_depth=press;app.refresh_all()
            messagebox.showinfo('Прижим ручки',f'Сохранён прижим {press:.3f} мм (касание Z={contact:.3f}, рабочая Z={float(z):.3f}).',parent=w)
        except Exception as exc:messagebox.showerror('Прижим ручки',str(exc),parent=w)
    def save_knife():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            app.checkpoint();app.project.material.work_z=float(z);app.refresh_all()
            messagebox.showinfo('Глубина ножа',f'Для материала «{app.project.material.name}» сохранена рабочая Z={float(z):.3f} мм.',parent=w)
        except Exception as exc:messagebox.showerror('Глубина ножа',str(exc),parent=w)
    def disconnect():
        c=client()
        if c is not None:
            try:c.close()
            except Exception:pass
        app._lan_client=None;conn_status.set('Не подключено');printer_status.set('Статус принтера: —');reset_z()
    def connect_now():
        if connecting['value']:return
        disconnect();connecting['value']=True;connect_btn.config(state='disabled');conn_status.set('Подключение…')
        try:save_cfg()
        except Exception:pass
        def worker():
            try:
                c=BambuLanClient(host.get().strip(),access.get().strip(),serial.get().strip());c.connect(timeout=7.0);err=None
            except Exception as exc:c=None;err=exc
            def finish():
                connecting['value']=False;connect_btn.config(state='normal')
                if err is not None:
                    conn_status.set('Ошибка подключения');messagebox.showerror('LAN подключение',str(err),parent=w);return
                app._lan_client=c;conn_status.set('Подключено');reset_z()
            try:app.after(0,finish)
            except Exception:
                if c is not None:c.close()
        threading.Thread(target=worker,daemon=True).start()
    def poll():
        try:
            if not w.winfo_exists():return
            c=client()
            if c is not None and c.connected:
                st=c.status_summary();state=str(st.get('gcode_state') or '—');last=last_state['value'];last_state['value']=state
                printer_status.set(f"Статус принтера: {state}   •   сопло {fmt(st.get('nozzle_temp'))}/{fmt(st.get('nozzle_target'))} °C   •   стол {fmt(st.get('bed_temp'))}/{fmt(st.get('bed_target'))} °C")
                conn_status.set('Подключено')
                if state.upper() not in ('IDLE','FINISH','FAILED','—') and last.upper() in ('IDLE','FINISH','FAILED','—'):
                    reset_z()
            elif not connecting['value']:
                conn_status.set('Не подключено')
            w.after(500,poll)
        except Exception:pass
    def closed():
        try:save_cfg()
        except Exception:pass
        disconnect();app._lan_window=None;w.destroy()
    connect_btn.config(command=connect_now);disconnect_btn.config(command=disconnect);sync_btn.config(command=do_sync)
    lower_btn.config(command=lambda:jog_z(-abs(float(step_var.get()))));raise_btn.config(command=lambda:jog_z(abs(float(step_var.get()))));return_btn.config(command=back_to_candidate);line_btn.config(command=test_line)
    save_contact_btn.config(command=save_contact);save_press_btn.config(command=save_press);save_knife_btn.config(command=save_knife)
    w.protocol('WM_DELETE_WINDOW',closed);poll()
