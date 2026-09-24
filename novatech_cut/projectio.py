import json
from .models import Project

def save_project(project: Project, filename: str):
    with open(filename,'w',encoding='utf-8') as f:json.dump(project.to_dict(),f,ensure_ascii=False,indent=2)

def load_project(filename: str) -> Project:
    with open(filename,'r',encoding='utf-8') as f:return Project.from_dict(json.load(f))
