from __future__ import annotations

import threading
import time
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
    w=tk.Toplevel(app);app._lan_window=w;w.title('LAN управление — Bambu Lab A1');w.geometry('840x900');w.minsize(760,700);w.transient(app)
    outer=ttk.Frame(w,padding=10);outer.pack(fill='both',expand=True)
    canvas=tk.Canvas(outer,highlightthickness=0);scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
    body=ttk.Frame(canvas);body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0,0),window=body,anchor='nw');canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    body.bind('<Configure>',lambda e:canvas.itemconfigure(canvas.find_all()[0],width=max(720,canvas.winfo_width()-4)) if canvas.find_all() else None)

    host=tk.StringVar(value=str(cfg.get('host','')));serial=tk.StringVar(value=str(cfg.get('serial','')));access=tk.StringVar(value=str(cfg.get('access_code','')))
    remember=tk.BooleanVar(value=bool(cfg.get('remember_access_code',False)))
    l,b,r,t=p.safe_bounds
    default_tx=min(230.0,max(l+15.0,r-15.0));default_ty=min(t-10.0,max(b+10.0,25.0))
    test_x=tk.DoubleVar(value=float(cfg.get('test_x',default_tx)));test_y=tk.DoubleVar(value=float(cfg.get('test_y',default_ty)))
    fine_step=tk.DoubleVar(value=float(cfg.get('z_step',0.10)));umts_removed=tk.BooleanVar(value=False)

    conn_status=tk.StringVar(value='Не подключено')
    printer_status=tk.StringVar(value='Статус принтера: —')
    feature_status=tk.StringVar(value='Orca-протокол: —')
    home_status=tk.StringVar(value='Home: не выполнен в этой сессии')
    pos_status=tk.StringVar(value='X: —   Y: —   Z: —')
    pos_source=tk.StringVar(value='Источник позиции: —')
    candidate_status=tk.StringVar(value='Z теста: —')

    candidate_z={'value':None};connecting={'value':False};homing={'active':False,'started':0.0,'seen_busy':False};homed={'value':False};last_state={'value':'—'}

    net=ttk.LabelFrame(body,text='Подключение к A1 по LAN',padding=10);net.pack(fill='x')
    net.columnconfigure(1,weight=1)
    for row,(lab,var,show) in enumerate([('IP принтера',host,''),('Серийный номер',serial,''),('LAN access code',access,'*')]):
        ttk.Label(net,text=lab,width=19).grid(row=row,column=0,sticky='w',pady=3)
        ttk.Entry(net,textvariable=var,show=show).grid(row=row,column=1,sticky='ew',pady=3,padx=(6,0))
    ttk.Checkbutton(net,text='Запомнить access code на этом компьютере',variable=remember).grid(row=3,column=0,columnspan=2,sticky='w',pady=(4,0))
    ttk.Label(net,text='Для сторонних LAN-команд на актуальной прошивке нужен LAN/Developer Mode.',foreground='#b45309',wraplength=760).grid(row=4,column=0,columnspan=2,sticky='w',pady=(6,2))
    bar=ttk.Frame(net);bar.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(8,0))
    connect_btn=ttk.Button(bar,text='Подключиться');connect_btn.pack(side='left')
    disconnect_btn=ttk.Button(bar,text='Отключиться');disconnect_btn.pack(side='left',padx=5)
    refresh_btn=ttk.Button(bar,text='Обновить статус');refresh_btn.pack(side='left')
    ttk.Label(bar,textvariable=conn_status).pack(side='left',padx=10)

    stat=ttk.LabelFrame(body,text='Состояние и координаты',padding=10);stat.pack(fill='x',pady=(10,0))
    ttk.Label(stat,textvariable=printer_status,style='Title.TLabel').pack(anchor='w')
    ttk.Label(stat,textvariable=feature_status).pack(anchor='w',pady=(3,0))
    ttk.Label(stat,textvariable=home_status).pack(anchor='w',pady=(3,0))
    ttk.Label(stat,textvariable=pos_status,font=('Segoe UI',15,'bold')).pack(anchor='w',pady=(8,0))
    ttk.Label(stat,textvariable=pos_source,foreground='#475569').pack(anchor='w',pady=(2,0))
    ttk.Label(stat,text='Если прошивка сама присылает XYZ — показываем их. Иначе Sibir Cut ведёт координаты после известного абсолютного перемещения и всех команд, отправленных из этой панели.',foreground='#475569',wraplength=760).pack(anchor='w',pady=(6,0))

    home=ttk.LabelFrame(body,text='Home с компьютера — как в OrcaSlicer',padding=10);home.pack(fill='x',pady=(10,0))
    ttk.Checkbutton(home,text='UMTS СНЯТ — можно выполнять Home',variable=umts_removed).pack(anchor='w')
    ttk.Label(home,text='На новой прошивке используется MQTT back_to_center. Если принтер это не поддерживает, применяется fallback G28. Во время активной печати полный Home заблокирован.',wraplength=750).pack(anchor='w',pady=(5,7))
    hr=ttk.Frame(home);hr.pack(fill='x')
    home_btn=ttk.Button(hr,text='HOME / вернуть голову домой');home_btn.pack(side='left',expand=True,fill='x')
    manual_home_btn=ttk.Button(hr,text='Home уже сделал на экране A1');manual_home_btn.pack(side='left',expand=True,fill='x',padx=(6,0))

    axis=ttk.LabelFrame(body,text='Управление осями — протокол OrcaSlicer',padding=10);axis.pack(fill='x',pady=(10,0))
    ttk.Label(axis,text='При поддержке прошивкой используются MQTT-команды xyz_ctrl. Кнопки ±1/±10 повторяют схему Orca.',wraplength=750).pack(anchor='w',pady=(0,6))
    grid=ttk.Frame(axis);grid.pack(fill='x')
    for col,txt in enumerate(['−10','−1','Ось','+1','+10']):
        ttk.Label(grid,text=txt,anchor='center').grid(row=0,column=col,sticky='ew',padx=2)
        grid.columnconfigure(col,weight=1)
    axis_buttons=[]
    for row,ax in enumerate(('X','Y','Z'),start=1):
        vals=(-10.0,-1.0,1.0,10.0)
        ttk.Label(grid,text=ax,font=('Segoe UI',11,'bold'),anchor='center').grid(row=row,column=2,sticky='ew',pady=2)
        for col,val in zip((0,1,3,4),vals):
            btn=ttk.Button(grid,text=f'{val:+.0f} мм')
            btn.grid(row=row,column=col,sticky='ew',padx=2,pady=2);axis_buttons.append((btn,ax,val))

    calib=ttk.LabelFrame(body,text='Точная настройка ножа / ручки на тестовом участке',padding=10);calib.pack(fill='x',pady=(10,0))
    pos=ttk.Frame(calib);pos.pack(fill='x',pady=(0,8))
    ttk.Label(pos,text='Точка КОНЧИКА инструмента X, мм').grid(row=0,column=0,sticky='w');ttk.Entry(pos,textvariable=test_x,width=9).grid(row=0,column=1,padx=(6,16))
    ttk.Label(pos,text='Y, мм').grid(row=0,column=2,sticky='w');ttk.Entry(pos,textvariable=test_y,width=9).grid(row=0,column=3,padx=6)
    sync_btn=ttk.Button(calib,text='1. Поднять на безопасную Z и перейти в тестовую точку');sync_btn.pack(fill='x',pady=(2,8))

    jog=ttk.LabelFrame(calib,text='Точная регулировка Z',padding=8);jog.pack(fill='x')
    jr=ttk.Frame(jog);jr.pack(fill='x')
    ttk.Label(jr,text='Шаг, мм').pack(side='left')
    ttk.Combobox(jr,textvariable=fine_step,values=[0.01,0.02,0.05,0.10,0.20,0.50,1.00],state='readonly',width=8).pack(side='left',padx=6)
    lower_btn=ttk.Button(jr,text='Ниже / СИЛЬНЕЕ');lower_btn.pack(side='left',expand=True,fill='x',padx=4)
    raise_btn=ttk.Button(jr,text='Выше / СЛАБЕЕ');raise_btn.pack(side='left',expand=True,fill='x',padx=4)
    ttk.Label(jog,textvariable=candidate_status).pack(anchor='w',pady=(6,0))

    test=ttk.LabelFrame(calib,text='Проверка на материале',padding=8);test.pack(fill='x',pady=(8,0))
    ttk.Label(test,text='На выбранной Z инструмент проведёт линию 10 мм и сразу поднимется обратно на безопасную Z.',wraplength=730).pack(anchor='w')
    line_btn=ttk.Button(test,text='Сделать тестовую линию 10 мм');line_btn.pack(fill='x',pady=(6,0))

    save=ttk.LabelFrame(calib,text='Сохранить настройку',padding=8);save.pack(fill='x',pady=(8,0))
    save_contact_btn=ttk.Button(save,text='Ручка: сохранить Z теста как ПЕРВОЕ касание');save_contact_btn.pack(fill='x',pady=2)
    save_press_btn=ttk.Button(save,text='Ручка: сохранить текущий прижим относительно первого касания');save_press_btn.pack(fill='x',pady=2)
    save_knife_btn=ttk.Button(save,text='Нож: сохранить Z теста как рабочую глубину');save_knife_btn.pack(fill='x',pady=2)

    def client():return getattr(app,'_lan_client',None)
    def fmt(v):
        try:return f'{float(v):.1f}'
        except Exception:return '—'
    def save_cfg():
        data={'host':host.get().strip(),'serial':serial.get().strip(),'remember_access_code':bool(remember.get()),'test_x':float(test_x.get()),'test_y':float(test_y.get()),'z_step':float(fine_step.get())}
        if remember.get():data['access_code']=access.get().strip()
        save_lan_config(data)
    def reset_position():
        c=client()
        if c is not None:c.invalidate_position()
        candidate_z['value']=None;candidate_status.set('Z теста: —')
    def set_candidate(v):
        candidate_z['value']=float(v);candidate_status.set(f'Z теста: {float(v):.3f} мм')
    def tool_point(line_len=0.0):
        tx=float(test_x.get());ty=float(test_y.get());l0,b0,r0,t0=app.project.printer.safe_bounds
        if not (l0<=tx<=r0 and b0<=ty<=t0 and l0<=tx+line_len<=r0):
            raise BambuLanError(f'Тестовый участок инструмента должен быть внутри безопасной зоны X {l0:.1f}…{r0:.1f}, Y {b0:.1f}…{t0:.1f} мм.')
        nx=tx-app.project.printer.tool_offset_x;ny=ty-app.project.printer.tool_offset_y;nx2=tx+line_len-app.project.printer.tool_offset_x
        if not (0<=nx<=app.project.printer.bed_width and 0<=nx2<=app.project.printer.bed_width and 0<=ny<=app.project.printer.bed_height):
            raise BambuLanError('С учётом Offset X/Y сопло вышло бы за физические границы стола.')
        return nx,ny,nx2
    def ready(require_home=True,require_pos=False):
        c=client()
        if c is None or not c.connected:raise BambuLanError('Сначала подключитесь к принтеру')
        state=str(c.status_summary().get('gcode_state','—')).upper()
        if state == '—':raise BambuLanError('Статус принтера ещё не получен')
        if state not in ('IDLE','FINISH','FAILED'):raise BambuLanError(f'Ручное управление заблокировано: состояние {state}')
        if require_home and not homed['value']:raise BambuLanError('Сначала выполните Home из этой панели или подтвердите, что Home уже сделан на A1')
        if require_pos:
            ps=c.position_snapshot()
            if ps.get('z') is None:raise BambuLanError('Координаты ещё не синхронизированы. Перейдите в тестовую точку.')
        return c
    def do_home():
        try:
            c=ready(require_home=False)
            if not umts_removed.get():raise BambuLanError('Снимите UMTS и поставьте галочку «UMTS СНЯТ».')
            if not messagebox.askyesno('Home A1','UMTS точно снят? Выполнить Home с компьютера?',parent=w):return
            method=c.go_home(printing=False);homed['value']=False;homing.update(active=True,started=time.monotonic(),seen_busy=False)
            home_status.set(f'Home выполняется… команда: {method}');candidate_z['value']=None;candidate_status.set('Z теста: —')
        except Exception as exc:messagebox.showerror('Home',str(exc),parent=w)
    def manual_home_done():
        if not umts_removed.get():
            messagebox.showwarning('Home','Сначала подтвердите, что UMTS снят.',parent=w);return
        homed['value']=True;reset_position();home_status.set('Home: подтверждён пользователем, координаты требуют синхронизации')
    def axis_jog(ax,val):
        try:
            c=ready(require_home=True)
            method=c.jog_axis_orca(ax,val,speed=3000,core_xy=False)
            if ax=='Z' and candidate_z['value'] is not None:
                candidate_z['value']=float(candidate_z['value'])+val
                candidate_status.set(f"Z теста: {candidate_z['value']:.3f} мм")
            home_status.set(f'Home: OK   •   последняя команда оси: {method}')
        except Exception as exc:messagebox.showerror('Ось '+ax,str(exc),parent=w)
    def do_sync():
        try:
            c=ready(require_home=True);nx,ny,_=tool_point();safe=max(float(app.project.printer.safe_z),float(app.project.material.safe_z))
            if not (app.project.printer.min_z<=safe<=app.project.printer.max_z):raise BambuLanError('Безопасная Z профиля вне допустимого диапазона')
            c.send_gcode(f'M104 S0\nM140 S0\nG90\nG1 Z{safe:.3f} F600\nM400\nG1 X{nx:.3f} Y{ny:.3f} F3000\nM400')
            c.set_known_position(x=nx,y=ny,z=safe,source='command');set_candidate(safe);save_cfg()
        except Exception as exc:messagebox.showerror('LAN калибровка',str(exc),parent=w)
    def fine_z(delta):
        try:
            c=ready(require_home=True,require_pos=True);ps=c.position_snapshot();nz=float(ps['z'])+float(delta)
            if not (app.project.printer.min_z<=nz<=app.project.printer.max_z):raise BambuLanError(f'Z {nz:.3f} мм вне диапазона профиля')
            c.move_absolute(z=nz,feed=120);set_candidate(nz);save_cfg()
        except Exception as exc:messagebox.showerror('Точная Z',str(exc),parent=w)
    def test_line():
        try:
            c=ready(require_home=True,require_pos=True);z=candidate_z['value']
            if z is None:raise BambuLanError('Сначала выберите Z теста')
            nx,ny,nx2=tool_point(10.0);safe=max(float(app.project.printer.safe_z),float(app.project.material.safe_z),float(z)+1.0);safe=min(safe,app.project.printer.max_z)
            c.send_gcode(f'G90\nG1 Z{safe:.3f} F600\nM400\nG1 X{nx:.3f} Y{ny:.3f} F2400\nM400\nG1 Z{float(z):.3f} F120\nM400\nG1 X{nx2:.3f} Y{ny:.3f} F300\nM400\nG1 Z{safe:.3f} F600\nM400')
            c.set_known_position(x=nx2,y=ny,z=safe,source='command');save_cfg()
        except Exception as exc:messagebox.showerror('Тестовая линия',str(exc),parent=w)
    def save_contact():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            app.checkpoint();app.project.printer.work_z=float(z);app.project.material.work_z=float(z);app.refresh_all()
            messagebox.showinfo('Калибровка ручки',f'Первое касание сохранено: Z={float(z):.3f} мм.',parent=w)
        except Exception as exc:messagebox.showerror('Калибровка ручки',str(exc),parent=w)
    def save_press():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            contact=float(app.project.printer.work_z);press=contact-float(z)
            if not (0.0<=press<=0.5):raise BambuLanError(f'Получился прижим {press:.3f} мм. Допустимый диапазон 0…0,5 мм.')
            app.checkpoint();app.project.material.drawing_press_depth=press;app.refresh_all()
            messagebox.showinfo('Прижим ручки',f'Сохранён прижим {press:.3f} мм.',parent=w)
        except Exception as exc:messagebox.showerror('Прижим ручки',str(exc),parent=w)
    def save_knife():
        try:
            z=candidate_z['value']
            if z is None:raise BambuLanError('Z теста ещё не выбрана')
            app.checkpoint();app.project.material.work_z=float(z);app.refresh_all()
            messagebox.showinfo('Глубина ножа',f'Сохранена рабочая Z={float(z):.3f} мм.',parent=w)
        except Exception as exc:messagebox.showerror('Глубина ножа',str(exc),parent=w)
    def refresh_status():
        c=client()
        if c is not None and c.connected:
            try:c.request_status()
            except Exception as exc:messagebox.showerror('LAN',str(exc),parent=w)
    def disconnect():
        c=client()
        if c is not None:
            try:c.close()
            except Exception:pass
        app._lan_client=None;conn_status.set('Не подключено');printer_status.set('Статус принтера: —');feature_status.set('Orca-протокол: —');homed['value']=False;homing['active']=False;home_status.set('Home: не выполнен в этой сессии');pos_status.set('X: —   Y: —   Z: —');pos_source.set('Источник позиции: —');candidate_z['value']=None;candidate_status.set('Z теста: —')
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
                app._lan_client=c;conn_status.set('Подключено');reset_position()
            try:app.after(0,finish)
            except Exception:
                if c is not None:c.close()
        threading.Thread(target=worker,daemon=True).start()
    def update_position_text(c):
        ps=c.position_snapshot();parts=[]
        for key in ('x','y','z'):
            v=ps.get(key);parts.append(f'{key.upper()}: {float(v):.3f}' if isinstance(v,(int,float)) else f'{key.upper()}: —')
        pos_status.set('   '.join(parts)+' мм')
        source={'printer':'принтер','command':'абсолютная команда Sibir Cut','tracked':'отслежено после команд','unknown':'—'}.get(str(ps.get('source')),'—')
        pos_source.set('Источник позиции: '+source)
    def poll():
        try:
            if not w.winfo_exists():return
            c=client()
            if c is not None and c.connected:
                st=c.status_summary();state=str(st.get('gcode_state') or '—');last=last_state['value'];last_state['value']=state
                printer_status.set(f"Статус: {state}   •   сопло {fmt(st.get('nozzle_temp'))}/{fmt(st.get('nozzle_target'))} °C   •   стол {fmt(st.get('bed_temp'))}/{fmt(st.get('bed_target'))} °C")
                feature_status.set('Orca-протокол: Home '+('MQTT back_to_center' if st.get('supports_mqtt_homing') else 'G28 fallback')+'   •   оси '+('MQTT xyz_ctrl' if st.get('supports_mqtt_axis_ctrl') else 'G-code fallback'))
                conn_status.set('Подключено');update_position_text(c)
                if homing['active']:
                    if state.upper() not in ('IDLE','FINISH','FAILED','—'):homing['seen_busy']=True
                    elapsed=time.monotonic()-homing['started']
                    if state.upper() in ('IDLE','FINISH') and (homing['seen_busy'] or elapsed>=5.0):
                        homing['active']=False;homed['value']=True;c.invalidate_position();home_status.set('Home: завершён. Теперь синхронизируйте XYZ переходом в тестовую точку.')
                    elif elapsed>45:
                        homing['active']=False;home_status.set('Home: не удалось подтвердить завершение — проверьте принтер.')
            elif not connecting['value']:
                conn_status.set('Не подключено')
            w.after(350,poll)
        except Exception:pass
    def closed():
        try:save_cfg()
        except Exception:pass
        disconnect();app._lan_window=None;w.destroy()

    connect_btn.config(command=connect_now);disconnect_btn.config(command=disconnect);refresh_btn.config(command=refresh_status)
    home_btn.config(command=do_home);manual_home_btn.config(command=manual_home_done)
    for btn,ax,val in axis_buttons:btn.config(command=lambda a=ax,v=val:axis_jog(a,v))
    sync_btn.config(command=do_sync);lower_btn.config(command=lambda:fine_z(-abs(float(fine_step.get()))));raise_btn.config(command=lambda:fine_z(abs(float(fine_step.get()))));line_btn.config(command=test_line)
    save_contact_btn.config(command=save_contact);save_press_btn.config(command=save_press);save_knife_btn.config(command=save_knife)
    w.protocol('WM_DELETE_WINDOW',closed);poll()
