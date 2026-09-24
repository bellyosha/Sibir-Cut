from pathlib import Path
from .geometry import load_svg, load_dxf, load_raster, remove_duplicate_paths, join_close_endpoints, simplify_path, optimize_order, compensate_dragknife, transformed_paths

RASTER_EXTENSIONS={'.png','.jpg','.jpeg','.bmp','.webp'}

def detect_import_kind(filename):
    path=Path(filename)
    if not path.exists() or not path.is_file():
        raise ValueError(f'Файл не найден: {filename}')
    try:
        with open(path,'rb') as fh:
            head=fh.read(16384)
    except OSError as exc:
        raise ValueError(f'Не удалось прочитать файл: {exc}') from exc

    # Binary image signatures MUST be checked before looking for "<svg".
    # Modern PNG/JUMBF metadata can legitimately embed SVG snippets
    # (for example image/svg+xml thumbnails), which does not make the
    # container itself an SVG file.
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'raster'
    if head.startswith(b'\xff\xd8\xff'):
        return 'raster'
    if head.startswith(b'BM'):
        return 'raster'
    if head.startswith((b'GIF87a',b'GIF89a')):
        return 'raster'
    if len(head)>=12 and head[:4]==b'RIFF' and head[8:12]==b'WEBP':
        return 'raster'

    low=head.lstrip(b'\xef\xbb\xbf\x00\t\r\n ').lower()
    # Treat as SVG only when the textual document starts with XML/SVG markup.
    if low.startswith(b'<svg') or (low.startswith(b'<?xml') and b'<svg' in low):
        return 'svg'

    ext=path.suffix.lower()
    if ext=='.dxf':
        return 'dxf'
    if ext=='.svg':
        raise ValueError(
            'Файл имеет расширение .svg, но внутри не найден SVG-код (<svg>). '
            'Возможно, это изображение с неправильным расширением.'
        )
    if ext in RASTER_EXTENSIONS:
        return 'raster'
    raise ValueError(f'Неподдерживаемый или неопознанный формат: {ext or "без расширения"}')

def import_paths(filename, **raster_opts):
    kind=detect_import_kind(filename)
    if kind=='svg': return load_svg(filename)
    if kind=='dxf': return load_dxf(filename)
    if kind=='raster': return load_raster(filename,**raster_opts)
    raise ValueError(f'Неизвестный тип файла: {kind}')

def prepare_paths(objects, material, join_tolerance=0.05, simplify_tolerance=0.03):
    paths=[]
    for obj in objects:paths.extend(transformed_paths(obj))
    paths=remove_duplicate_paths(paths)
    paths=join_close_endpoints(paths,join_tolerance)
    paths=[simplify_path(p,simplify_tolerance) for p in paths]
    paths=optimize_order(paths)
    if material.mode=='Резка' and material.blade_offset>0:
        paths=[compensate_dragknife(p,material.blade_offset,material.overcut) for p in paths]
    if material.mirror_x:
        from .geometry import bbox
        x0,_,x1,_=bbox(paths);cx=(x0+x1)/2
        paths=[[(2*cx-x,y) for x,y in p] for p in paths]
    return paths
