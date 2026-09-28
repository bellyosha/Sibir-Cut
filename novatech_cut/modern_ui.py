from __future__ import annotations

import tkinter as tk


def _rounded_points(x1, y1, x2, y2, r):
    r=max(0,min(r,(x2-x1)/2,(y2-y1)/2))
    return [
        x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
        x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
        x1,y2, x1,y2-r, x1,y1+r, x1,y1,
    ]


class RoundedButton(tk.Canvas):
    def __init__(
        self,parent,text,command=None,width=180,height=42,radius=13,
        bg="#0f766e",fg="white",hover="#115e59",font=("Segoe UI",10,"bold"),
        disabled_bg="#cbd5e1",disabled_fg="#64748b",**kwargs
    ):
        parent_bg=kwargs.pop("parent_bg",None)
        if parent_bg is None:
            try: parent_bg=parent.cget("background")
            except Exception: parent_bg="#f4f6f8"
        super().__init__(parent,width=width,height=height,highlightthickness=0,borderwidth=0,bg=parent_bg,**kwargs)
        self._text=text;self._command=command;self._radius=radius
        self._bg=bg;self._fg=fg;self._hover=hover;self._font=font
        self._disabled_bg=disabled_bg;self._disabled_fg=disabled_fg;self._state="normal"
        self.bind("<Configure>",lambda e:self._draw())
        self.bind("<Enter>",lambda e:self._draw(self._hover if self._state=="normal" else self._disabled_bg))
        self.bind("<Leave>",lambda e:self._draw())
        self.bind("<Button-1>",self._click)
        self._draw()

    def _draw(self,fill=None):
        self.delete("all");w=max(2,self.winfo_width());h=max(2,self.winfo_height())
        color=fill or (self._bg if self._state=="normal" else self._disabled_bg)
        fg=self._fg if self._state=="normal" else self._disabled_fg
        self.create_polygon(_rounded_points(1,1,w-1,h-1,self._radius),smooth=True,splinesteps=24,fill=color,outline="")
        self.create_text(w/2,h/2,text=self._text,fill=fg,font=self._font)

    def _click(self,event=None):
        if self._state=="normal" and self._command:
            self._command()

    def config(self,cnf=None,**kwargs):
        if cnf:
            kwargs.update(cnf)
        if "text" in kwargs:self._text=kwargs.pop("text")
        if "command" in kwargs:self._command=kwargs.pop("command")
        if "state" in kwargs:self._state=kwargs.pop("state")
        if "bg" in kwargs:self._bg=kwargs.pop("bg")
        if "fg" in kwargs:self._fg=kwargs.pop("fg")
        if "hover" in kwargs:self._hover=kwargs.pop("hover")
        if kwargs:return super().config(**kwargs)
        self._draw()

    configure=config


class RoundedPanel(tk.Canvas):
    def __init__(self,parent,radius=18,fill="#ffffff",outline="#e5e7eb",pad=14,height=120,**kwargs):
        parent_bg=kwargs.pop("parent_bg",None)
        if parent_bg is None:
            try: parent_bg=parent.cget("background")
            except Exception: parent_bg="#f4f6f8"
        super().__init__(parent,height=height,highlightthickness=0,borderwidth=0,bg=parent_bg,**kwargs)
        self._radius=radius;self._fill=fill;self._outline=outline;self._pad=pad
        self.inner=tk.Frame(self,bg=fill,highlightthickness=0,borderwidth=0)
        self._window=self.create_window(pad,pad,window=self.inner,anchor="nw")
        self.bind("<Configure>",self._resize)

    def _resize(self,event=None):
        w=max(2,self.winfo_width());h=max(2,self.winfo_height());p=self._pad
        self.delete("panel")
        self.create_polygon(_rounded_points(1,1,w-1,h-1,self._radius),smooth=True,splinesteps=24,fill=self._fill,outline=self._outline,width=1,tags="panel")
        self.tag_lower("panel")
        self.itemconfigure(self._window,width=max(1,w-2*p),height=max(1,h-2*p))
