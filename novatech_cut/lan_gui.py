from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .lan import BambuLanClient, BambuLanError, load_lan_config, save_lan_config
from .discovery import BambuLanScanner, DiscoveredPrinter
from .transfer import upload_file, BambuTransferError, UploadCancelled


def upload_path_via_lan(app, path, parent=None, on_done=None):
    """Upload an already generated G-code to the connected printer over FTPS."""
    parent=parent or app
    client=getattr(app,'_lan_client',None)
    if client is None or not getattr(client,'connected',False):
        messagebox.showerror('Отправка по LAN','Сначала подключитесь к принтеру в окне «LAN управление».',parent=parent)
        if on_done:
            try:on_done(None,'Нет подключения к принтеру')
            except Exception:pass
        return False
    if getattr(app,'_lan_upload_busy',False):
        messagebox.showwarning('Отправка по LAN','Передача файла уже выполняется.',parent=parent);return False

    cancel=threading.Event();app._lan_upload_busy=True
    win=tk.Toplevel(parent);win.title('Отправка файла на Bambu');win.transient(parent);win.resizable(False,False)
    box=ttk.Frame(win,padding=14);box.pack(fill='both',expand=True)
    ttk.Label(box,text='Передача по LAN → FTPS/TLS 990',style='Title.TLabel').pack(anchor='w')
    name=str(path).replace('\\','/').split('/')[-1]
    status=tk.StringVar(value=f'Подготовка: {name}')
    ttk.Label(box,textvariable=status,wraplength=480).pack(anchor='w',pady=(8,4))
    pb=ttk.Progressbar(box,mode='determinate',maximum=100);pb.pack(fill='x',pady=5)
    cancel_btn=ttk.Button(box,text='Отменить',command=cancel.set);cancel_btn.pack(anchor='e',pady=(6,0))
    def progress(sent,total):
        pct=0 if not total else min(100.0,max(0.0,sent*100.0/total))
        try:app.after(0,lambda p=pct,s=sent,t=total:(pb.configure(value=p),status.set(f'Передача: {p:.0f}% • {s}/{t} байт')))
        except Exception:pass
    def worker():
        result=None;err=None
        try:result=upload_file(client.host,client.access_code,path,progress=progress,cancel=cancel)
        except Exception as exc:err=exc
        def finish():
            app._lan_upload_busy=False
            try:win.destroy()
            except Exception:pass
            if err is None:
                verified='размер проверен' if result.get('verified_size') else 'сервер подтвердил STOR'
                messagebox.showinfo('Отправка по LAN',f"Файл отправлен на A1.\n\n{result.get('remote_path')}\n{result.get('size_bytes')} байт • {verified}\n\nАвтоматический запуск задания не выполнялся.",parent=parent)
                if on_done:
                    try:on_done(result,None)
                    except Exception:pass
            else:
                if not isinstance(err,UploadCancelled):
                    messagebox.showerror('Отправка по LAN',str(err),parent=parent)
                if on_done:
                    try:on_done(None,str(err))
                    except Exception:pass
        try:app.after(0,finish)
        except Exception:pass
    threading.Thread(target=worker,daemon=True).start()
    return True


def open_lan_control(app):
    old=getattr(app,'_lan_window',None)
    if old is not None:
        try:
            if old.winfo_exists():old.lift();return
        except Exception:pass

    cfg=load_lan_config();p=app.project.printer
    w=tk.Toplevel(app);app._lan_window=w;w.title('LAN управление — Bambu Lab A1');w.transient(app)
    w.resizable(True,True)
    sw=max(800,int(w.winfo_screenwidth()));sh=max(700,int(w.winfo_screenheight()))
    initial_w=min(980,max(760,sw-120));initial_h=min(900,max(620,sh-120))
    w.geometry(f'{initial_w}x{initial_h}')
    w.minsize(680,520)

    outer=ttk.Frame(w,padding=10);outer.pack(fill='both',expand=True)
    outer.columnconfigure(0,weight=1);outer.rowconfigure(0,weight=1)
    canvas=tk.Canvas(outer,highlightthickness=0,borderwidth=0)
    scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
    canvas.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
    body=ttk.Frame(canvas)
    body_window=canvas.create_window((0,0),window=body,anchor='nw')
    canvas.configure(yscrollcommand=scroll.set)

    def _update_scrollregion(event=None):
        try:canvas.configure(scrollregion=canvas.bbox('all'))
        except Exception:pass
    def _fit_body_width(event):
        try:canvas.itemconfigure(body_window,width=max(1,int(event.width)))
        except Exception:pass
    def _scroll_units(delta):
        try:
            first,last=canvas.yview()
            if first<=0.0 and delta<0:return
            if last>=1.0 and delta>0:return
            canvas.yview_scroll(int(delta),'units')
        except Exception:pass
    def _mousewheel(event):
        # Windows/macOS wheel. Keep the whole LAN page scrollable even when
        # the cursor is over buttons, entries or the printer table.
        raw=getattr(event,'delta',0)
        if raw:
            steps=-max(1,abs(int(raw))//120) if raw>0 else max(1,abs(int(raw))//120)
            _scroll_units(steps)
            return 'break'
    def _linux_wheel(event):
        num=getattr(event,'num',0)
        if num==4:_scroll_units(-3)
        elif num==5:_scroll_units(3)
        return 'break'

    body.bind('<Configure>',_update_scrollregion)
    canvas.bind('<Configure>',_fit_body_width)
    w.bind('<MouseWheel>',_mousewheel,add='+')
    w.bind('<Button-4>',_linux_wheel,add='+')
    w.bind('<Button-5>',_linux_wheel,add='+')
    w.bind('<Prior>',lambda e:(canvas.yview_scroll(-1,'pages'),'break')[1],add='+')
    w.bind('<Next>',lambda e:(canvas.yview_scroll(1,'pages'),'break')[1],add='+')
    w.bind('<Home>',lambda e:(canvas.yview_moveto(0.0),'break')[1],add='+')
    w.bind('<End>',lambda e:(canvas.yview_moveto(1.0),'break')[1],add='+')

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
    scanner={'obj':None,'running':False};discovered={};scan_status=tk.StringVar(value='Поиск ещё не запускался')
    tool_choice=tk.StringVar(value='Ручка' if app.project.material.mode=='Рисование' else 'Нож')
    offset_step=tk.DoubleVar(value=0.5);ref_x=tk.DoubleVar(value=float(cfg.get('offset_ref_x',128.0)));ref_y=tk.DoubleVar(value=float(cfg.get('offset_ref_y',128.0)))
    offset_ref={'x':None,'y':None};offset_status=tk.StringVar(value='Offset X/Y ещё не откалиброван в этой сессии')
    upload_status=tk.StringVar(value='Файл ещё не отправлялся');upload_state={'busy':False,'cancel':None}

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

    scanbox=ttk.LabelFrame(body,text='Принтеры Bambu в локальной сети',padding=10);scanbox.pack(fill='x',pady=(10,0))
    sbar=ttk.Frame(scanbox);sbar.pack(fill='x')
    scan_btn=ttk.Button(sbar,text='Сканировать сеть');scan_btn.pack(side='left')
    stop_scan_btn=ttk.Button(sbar,text='Остановить',state='disabled');stop_scan_btn.pack(side='left',padx=5)
    use_scan_btn=ttk.Button(sbar,text='Выбрать принтер');use_scan_btn.pack(side='left')
    ttk.Label(sbar,textvariable=scan_status).pack(side='left',padx=10)
    cols=('name','model','ip','serial','signal','source')
    printer_tree=ttk.Treeview(scanbox,columns=cols,show='headings',height=5,selectmode='browse')
    for key,title,width in [
        ('name','Имя',140),('model','Модель',150),('ip','IP',110),
        ('serial','Серийный номер',165),('signal','Сигнал',65),('source','Источник',85)
    ]:
        printer_tree.heading(key,text=title);printer_tree.column(key,width=width,anchor='w',stretch=(key in ('name','model','serial')))
    printer_tree.pack(fill='x',pady=(8,0))
    ttk.Label(scanbox,text='Access code по сети не передаётся. После выбора принтера введите его один раз вручную или включите «Запомнить access code».',foreground='#475569',wraplength=760).pack(anchor='w',pady=(6,0))

    files_box=ttk.LabelFrame(body,text='Файлы по LAN',padding=10);files_box.pack(fill='x',pady=(10,0))
    fr=ttk.Frame(files_box);fr.pack(fill='x')
    send_last_btn=ttk.Button(fr,text='Отправить последний экспорт');send_last_btn.pack(side='left',expand=True,fill='x')
    send_file_btn=ttk.Button(fr,text='Выбрать .gcode и отправить…');send_file_btn.pack(side='left',expand=True,fill='x',padx=(6,0))
    cancel_upload_btn=ttk.Button(fr,text='Отмена передачи',state='disabled');cancel_upload_btn.pack(side='left',padx=(6,0))
    ttk.Label(files_box,textvariable=upload_status).pack(anchor='w',pady=(6,0))
    ttk.Label(files_box,text='Файл загружается на принтер локально по FTPS/TLS в папку cache. Автоматический запуск пока не выполняется.',foreground='#475569',wraplength=760).pack(anchor='w',pady=(3,0))

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

    offset_box=ttk.LabelFrame(body,text='Калибровка Offset X/Y — где нож/ручка относительно сопла',padding=10);offset_box.pack(fill='x',pady=(10,0))
    topoff=ttk.Frame(offset_box);topoff.pack(fill='x')
    ttk.Label(topoff,text='Калибруем:').pack(side='left')
    ttk.Combobox(topoff,textvariable=tool_choice,values=['Нож','Ручка'],state='readonly',width=12).pack(side='left',padx=(6,16))
    ttk.Label(topoff,text='Опорная точка сопла X').pack(side='left');ttk.Entry(topoff,textvariable=ref_x,width=8).pack(side='left',padx=4)
    ttk.Label(topoff,text='Y').pack(side='left');ttk.Entry(topoff,textvariable=ref_y,width=8).pack(side='left',padx=4)
    ref_btn=ttk.Button(offset_box,text='1. Поставить СОПЛО в опорную точку');ref_btn.pack(fill='x',pady=(8,4))
    ttk.Label(offset_box,text='После перемещения отметьте точку прямо под соплом на бумаге/малярной ленте. Затем установите UMTS и, не меняя метку, подведите к ней кончик выбранного инструмента.',wraplength=750).pack(anchor='w',pady=(2,6))
    fine=ttk.Frame(offset_box);fine.pack(fill='x')
    ttk.Label(fine,text='Шаг XY, мм').pack(side='left')
    ttk.Combobox(fine,textvariable=offset_step,values=[0.05,0.10,0.20,0.50,1.00],state='readonly',width=8).pack(side='left',padx=6)
    xy_buttons=[]
    for txt,ax,sgn in [('X −','X',-1),('X +','X',1),('Y −','Y',-1),('Y +','Y',1)]:
        bxy=ttk.Button(fine,text=txt);bxy.pack(side='left',expand=True,fill='x',padx=2);xy_buttons.append((bxy,ax,sgn))
    calc_offset_btn=ttk.Button(offset_box,text='2. Кончик на метке — рассчитать и сохранить Offset X/Y');calc_offset_btn.pack(fill='x',pady=(8,4))
    ttk.Label(offset_box,textvariable=offset_status).pack(anchor='w')

    calib=ttk.LabelFrame(body,text='Точная настройка Z ножа / ручки на тестовом участке',padding=10);calib.pack(fill='x',pady=(10,0))
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
        codes=cfg.get('access_codes',{}) if isinstance(cfg.get('access_codes',{}),dict) else {}
        sn=serial.get().strip();code=access.get().strip()
        data={'host':host.get().strip(),'serial':sn,'remember_access_code':bool(remember.get()),'test_x':float(test_x.get()),'test_y':float(test_y.get()),'z_step':float(fine_step.get()),'access_codes':dict(codes)}
        if remember.get():
            data['access_code']=code
            if sn and code:data['access_codes'][sn]=code
        save_lan_config(data)
        cfg.clear();cfg.update(data)
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
    def _printer_key(p):
        return str(p.serial or p.ip)
    def _source_name(source):
        return 'SSDP' if source=='ssdp' else ('MQTT 8883' if source=='tcp' else str(source or '—'))
    def add_discovered(p):
        try:
            key=_printer_key(p);discovered[key]=p
            values=(p.name or '—',p.model_name or p.model_code or 'Bambu Lab',p.ip,p.serial or '—',p.signal or '—',_source_name(p.source))
            if printer_tree.exists(key):printer_tree.item(key,values=values)
            else:printer_tree.insert('', 'end', iid=key, values=values)
            real=sum(1 for x in discovered.values() if x.serial)
            candidates=len(discovered)-real
            scan_status.set(f'Найдено: {real} Bambu' + (f' + {candidates} кандид.' if candidates else ''))
        except Exception:pass
    def scan_finished(items):
        scanner['running']=False
        try:scan_btn.config(state='normal');stop_scan_btn.config(state='disabled')
        except Exception:return
        real=sum(1 for x in items if x.serial);candidates=len(items)-real
        if items:
            scan_status.set(f'Готово: {real} Bambu' + (f', {candidates} кандид. по 8883' if candidates else ''))
        else:
            scan_status.set('Ничего не найдено. Проверьте Wi‑Fi/LAN и брандмауэр Windows.')
    def scan_network():
        if scanner['running']:return
        old=scanner.get('obj')
        if old is not None:
            try:old.stop()
            except Exception:pass
        discovered.clear()
        for iid in printer_tree.get_children():
            printer_tree.delete(iid)
        scanner['running']=True;scan_status.set('Сканирование… до 6 секунд');scan_btn.config(state='disabled');stop_scan_btn.config(state='normal')
        def found_cb(p):
            try:app.after(0,lambda pp=p:add_discovered(pp))
            except Exception:pass
        def done_cb(items):
            try:app.after(0,lambda ii=items:scan_finished(ii))
            except Exception:pass
        sc=BambuLanScanner(on_printer=found_cb,on_done=done_cb);scanner['obj']=sc
        threading.Thread(target=lambda:sc.scan(5.5),daemon=True).start()
    def stop_scan():
        sc=scanner.get('obj')
        if sc is not None:
            try:sc.stop()
            except Exception:pass
        scanner['running']=False;scan_btn.config(state='normal');stop_scan_btn.config(state='disabled');scan_status.set('Сканирование остановлено')
    def use_selected_printer(event=None):
        sel=printer_tree.selection()
        if not sel:return
        p=discovered.get(sel[0])
        if p is None:return
        host.set(p.ip)
        if p.serial:
            serial.set(p.serial)
            codes=cfg.get('access_codes',{}) if isinstance(cfg.get('access_codes',{}),dict) else {}
            if p.serial in codes and codes[p.serial]:access.set(str(codes[p.serial]))
            scan_status.set(f'Выбран: {p.display_name()} • {p.ip}')
        else:
            scan_status.set(f'Выбран IP {p.ip}; SSDP не сообщил серийный номер — введите SN вручную.')
        try:save_cfg()
        except Exception:pass
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
        sc=scanner.get('obj')
        if sc is not None:
            try:sc.stop()
            except Exception:pass
        disconnect();app._lan_window=None;w.destroy()

    connect_btn.config(command=connect_now);disconnect_btn.config(command=disconnect);refresh_btn.config(command=refresh_status)
    scan_btn.config(command=scan_network);stop_scan_btn.config(command=stop_scan);use_scan_btn.config(command=use_selected_printer);printer_tree.bind('<Double-1>',use_selected_printer)
    home_btn.config(command=do_home);manual_home_btn.config(command=manual_home_done)
    for btn,ax,val in axis_buttons:btn.config(command=lambda a=ax,v=val:axis_jog(a,v))
    sync_btn.config(command=do_sync);lower_btn.config(command=lambda:fine_z(-abs(float(fine_step.get()))));raise_btn.config(command=lambda:fine_z(abs(float(fine_step.get()))));line_btn.config(command=test_line)
    save_contact_btn.config(command=save_contact);save_press_btn.config(command=save_press);save_knife_btn.config(command=save_knife)
    w.protocol('WM_DELETE_WINDOW',closed);poll();w.after(350,scan_network)
