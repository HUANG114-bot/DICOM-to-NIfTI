#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows-friendly batch DICOM -> NIfTI converter (Tkinter).

Non-destructive: keeps all original DICOMs untouched. Does NOT anonymize images,
source folder names or CSV; handle generated reports as sensitive patient data.
"""
from __future__ import annotations

import csv
import hashlib
import os
import queue
import re
import threading
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import dicom2nifti
import nibabel as nib
import numpy as np
import pydicom

HEADER_TAGS = [
    "PatientID", "PatientName", "StudyDate", "StudyDescription", "StudyInstanceUID",
    "SeriesInstanceUID", "SeriesNumber", "SeriesDescription", "SOPInstanceUID",
    "InstanceNumber", "Modality", "Rows", "Columns", "ImagePositionPatient",
    "ImageOrientationPatient", "PixelSpacing", "SliceThickness", "NumberOfFrames",
    "ContrastBolusAgent", "ContrastBolusRoute", "ImageType", "AcquisitionNumber",
]
SERIES_COLS = ["status", "nifti_relative_path", "patient_id", "patient_name", "study_date",
               "study_description", "study_uid", "series_uid", "series_number",
               "series_description", "modality", "contrast_bolus_agent", "dicom_count",
               "nifti_shape", "nifti_spacing_mm", "output_folder", "error"]
FILE_COLS = ["status", "nifti_relative_path", "source_relative_path", "dicom_filename",
             "patient_id", "study_uid", "series_uid", "sop_instance_uid", "instance_number",
             "image_position_patient", "error"]


def txt(v):
    return str(v) if v is not None else ""


def safe_name(value: str, limit: int = 55):
    name = re.sub(r'[^A-Za-z0-9_-]+', '_', value or '')
    return name.strip('_')[:limit] or "Series"


def digest(value: str):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]


@dataclass(frozen=True)
class Entry:
    path: Path
    relative_path: Path
    pid: str
    pname: str
    study_date: str
    study_description: str
    study_uid: str
    series_uid: str
    series_number: str
    series_description: str
    sop_uid: str
    instance_number: str
    modality: str
    rows: int
    cols: int
    image_position: str
    contrast_agent: str


def read_header(item):
    path, root = item
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True,
                             specific_tags=HEADER_TAGS, force=False)
        if (not ds.get('SeriesInstanceUID') or not ds.get('StudyInstanceUID')
                or not ds.get('SOPInstanceUID') or not ds.get('Rows') or not ds.get('Columns')):
            return None
        return Entry(
            path=path, relative_path=path.relative_to(root),
            pid=txt(ds.get('PatientID')), pname=txt(ds.get('PatientName')),
            study_date=txt(ds.get('StudyDate')), study_description=txt(ds.get('StudyDescription')),
            study_uid=txt(ds.get('StudyInstanceUID')), series_uid=txt(ds.get('SeriesInstanceUID')),
            series_number=txt(ds.get('SeriesNumber')),
            series_description=txt(ds.get('SeriesDescription')),
            sop_uid=txt(ds.get('SOPInstanceUID')), instance_number=txt(ds.get('InstanceNumber')),
            modality=txt(ds.get('Modality')), rows=int(ds.Rows), cols=int(ds.Columns),
            image_position=txt(ds.get('ImagePositionPatient')),
            contrast_agent=txt(ds.get('ContrastBolusAgent')))
    except Exception:
        return None


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def check_paths(source: str, dest: str):
    root = Path(source).expanduser().resolve()
    out = Path(dest).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('來源資料夾不存在或無法讀取。')
    if is_relative_to(out, root) or is_relative_to(root, out):
        raise ValueError('來源和輸出路徑不能相同或互相包含，避免重複掃描及覆蓋風險。')
    if out.exists() and not out.is_dir():
        raise ValueError('輸出位置必須是資料夾。')
    if out.exists() and any(out.iterdir()):
        raise ValueError('輸出資料夾不是空的。請選擇新的資料夾，以避免混淆舊資料。')
    return root, out


def scan(root: Path, send: Callable):
    groups = defaultdict(list)
    dirs = set()
    scanned = skipped = 0
    batch = []
    def consume(pool):
        nonlocal scanned, skipped
        for entry in pool.map(read_header, batch):
            scanned += 1
            if entry is None:
                skipped += 1
            else:
                # Series UID is the primary DICOM grouping key, independent of folder layout.
                groups[(entry.study_uid, entry.series_uid)].append(entry)
        batch.clear()
        send('scan', (scanned, skipped, len(groups)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        def walk_error(err):
            send('log', '資料夾無法讀取：' + str(err))
        for folder, subdirs, filenames in os.walk(root, onerror=walk_error):
            subdirs.sort()
            filenames.sort()
            dirs.add(Path(folder).relative_to(root))
            for filename in filenames:
                batch.append((Path(folder) / filename, root))
                if len(batch) >= 100:
                    consume(pool)
        if batch:
            consume(pool)
    send('scan', (scanned, skipped, len(groups)))
    return groups, dirs, skipped


def series_location(entries):
    # If a series is spread across folders, use its common ancestor beneath root.
    folders = [str(e.relative_path.parent) for e in entries]
    if len(folders) == 1:
        return entries[0].relative_path.parent
    relative = os.path.commonpath(folders)
    return Path(relative)


def verify_nii(path: Path):
    img = nib.load(str(path))
    shape = tuple(int(n) for n in img.shape)
    if len(shape) < 3 or min(shape[:3]) < 1:
        raise ValueError('輸出不是有效的 3D / 4D 醫學影像')
    zooms = tuple(float(v) for v in img.header.get_zooms()[:3])
    if any(not np.isfinite(z) or z <= 0 for z in zooms):
        raise ValueError('NIfTI spacing 無效')
    if not np.all(np.isfinite(img.affine)) or abs(float(np.linalg.det(img.affine[:3, :3]))) < 1e-10:
        raise ValueError('NIfTI 座標矩陣無效')
    # Full scan verifies gzip data and checks for corrupt/unreadable values.
    values = np.asanyarray(img.dataobj)
    if not np.all(np.isfinite(values)):
        raise ValueError('NIfTI 像素包含 NaN/Infinity')
    return 'x'.join(map(str, shape)), ','.join(f'{z:.5g}' for z in zooms)


def convert(entries, out: Path, relfolder: Path, basename: str):
    folder = out / relfolder
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / (basename + '.nii.gz')
    tmp = folder / (basename + '.partial.nii.gz')
    if final.exists() or tmp.exists():
        raise FileExistsError('同名輸出已存在：' + final.name)
    try:
        datasets = [pydicom.dcmread(str(e.path)) for e in entries]
        # This API converts in-memory DICOM datasets; original files are unchanged.
        dicom2nifti.convert_dicom.dicom_array_to_nifti(datasets, str(tmp), reorient_nifti=True)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError('轉換器沒有輸出影像')
        shape, spacing = verify_nii(tmp)
        tmp.replace(final)
        return final.relative_to(out).as_posix(), shape, spacing
    finally:
        if tmp.exists():
            tmp.unlink()


def run(source: str, destination: str, send: Callable):
    root, out = check_paths(source, destination)
    send('log', '掃描 DICOM 檔案（包含所有子資料夾）…')
    groups, dirs, skipped = scan(root, send)
    send('log', f'掃描完成：{len(groups)} 組 Study/Series、{skipped} 個非影像或無法辨識的檔案')
    if not groups:
        raise ValueError('找不到具有必要影像欄位的 DICOM。')
    # Prevent accidentally converting the same instance twice. A repeated SOP
    # instance is treated as an error rather than silently removing images.
    out.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (out / d).mkdir(parents=True, exist_ok=True)
    send('total', len(groups))
    series_rows, file_rows = [], []
    failed_examples = []
    successful = failed = 0
    ordered = sorted(groups.values(), key=lambda v: min(str(e.relative_path).lower() for e in v))
    for idx, original_entries in enumerate(ordered, 1):
        entries = sorted(original_entries, key=lambda e: str(e.relative_path).lower())
        f = entries[0]
        # Study/Series grouping across folders can have mixed image dimensions;
        # let dicom2nifti validate geometry rather than silently merging wrongly.
        relfolder = series_location(entries)
        base = f"{safe_name(f.modality, 8)}_S{safe_name(f.series_number, 12)}_{digest(f.study_uid + '|' + f.series_uid)}"
        relative_nifti = ''
        shape = spacing = err = ''
        status = 'OK'
        try:
            seen = set()
            for e in entries:
                if e.sop_uid in seen:
                    raise ValueError('同一序列包含重複 SOPInstanceUID；請檢查來源是否有重複匯出')
                seen.add(e.sop_uid)
            # Reject clearly mixed dimensions before conversion.
            if len({(e.rows, e.cols) for e in entries}) > 1:
                raise ValueError('同一 Series 有不同 Rows/Columns，不能直接合成單一 3D 影像')
            relative_nifti, shape, spacing = convert(entries, out, relfolder, base)
            successful += 1
        except Exception as exc:
            status = 'ERROR'
            err = f'{type(exc).__name__}: {exc}'
            failed += 1
            if len(failed_examples) < 8:
                failed_examples.append(f'{base}: {err[:150]}')
            send('log', f'[{idx}/{len(ordered)}] 失敗：{base} — {err[:200]}')
        else:
            send('log', f'[{idx}/{len(ordered)}] 成功：{relative_nifti}')
        series_rows.append({
            'status': status, 'nifti_relative_path': relative_nifti,
            'patient_id': f.pid, 'patient_name': f.pname, 'study_date': f.study_date,
            'study_description': f.study_description, 'study_uid': f.study_uid,
            'series_uid': f.series_uid, 'series_number': f.series_number,
            'series_description': f.series_description, 'modality': f.modality,
            'contrast_bolus_agent': f.contrast_agent, 'dicom_count': len(entries),
            'nifti_shape': shape, 'nifti_spacing_mm': spacing,
            'output_folder': relfolder.as_posix(), 'error': err})
        for e in entries:
            file_rows.append({
                'status': status, 'nifti_relative_path': relative_nifti,
                'source_relative_path': e.relative_path.as_posix(),
                'dicom_filename': e.path.name, 'patient_id': e.pid,
                'study_uid': e.study_uid, 'series_uid': e.series_uid,
                'sop_instance_uid': e.sop_uid, 'instance_number': e.instance_number,
                'image_position_patient': e.image_position, 'error': err})
        send('progress', (idx, len(ordered), successful, failed))
    for filename, fields, rows in (
        ('conversion_report.csv', SERIES_COLS, series_rows),
        ('dicom_file_mapping.csv', FILE_COLS, file_rows),
    ):
        with (out / filename).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return successful, failed, skipped, str(out / 'conversion_report.csv'), failed_examples


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    win = tk.Tk()
    win.title('DICOM → NIfTI｜批次轉換工具')
    win.geometry('830x570')
    win.minsize(690, 480)
    win.columnconfigure(0, weight=1)
    win.rowconfigure(3, weight=1)
    events = queue.Queue()
    source = tk.StringVar()
    dest = tk.StringVar()
    status = tk.StringVar(value='就緒')
    counts = tk.StringVar(value='成功 0　｜　失敗 0　｜　待處理 0')
    active = False

    top = ttk.Frame(win, padding=(16, 14))
    top.grid(row=0, column=0, sticky='ew')
    top.columnconfigure(0, weight=1)
    ttk.Label(top, text='DICOM 批次轉 NIfTI', font=('Microsoft JhengHei UI', 16, 'bold')).grid(row=0, column=0, sticky='w')
    ttk.Label(top, text='自動掃描所有子資料夾、依序列轉檔、原始資料完全不修改').grid(row=1, column=0, sticky='w', pady=(3, 0))

    paths = ttk.Frame(win, padding=(16, 0))
    paths.grid(row=1, column=0, sticky='ew')
    paths.columnconfigure(0, weight=1)
    ttk.Label(paths, text='1. 選擇整包 DICOM 來源資料夾').grid(row=0, column=0, sticky='w')
    ttk.Entry(paths, textvariable=source).grid(row=1, column=0, sticky='ew', pady=(4, 10))
    def pick_source():
        selection = filedialog.askdirectory(parent=win, title='選擇來源 DICOM 資料夾')
        if selection:
            source.set(selection)
            if not dest.get().strip():
                p = Path(selection)
                dest.set(str(p.parent / (p.name + '_NIFTI')))
    ttk.Button(paths, text='瀏覽來源…', command=pick_source).grid(row=1, column=1, padx=(8, 0), pady=(4, 10))
    ttk.Label(paths, text='2. 新的 NIfTI 輸出資料夾（自動複製原有資料夾階層）').grid(row=2, column=0, sticky='w')
    ttk.Entry(paths, textvariable=dest).grid(row=3, column=0, sticky='ew', pady=(4, 7))
    ttk.Button(paths, text='瀏覽輸出…', command=lambda: dest.set(filedialog.askdirectory(parent=win, title='選擇空的輸出資料夾') or dest.get())).grid(row=3, column=1, padx=(8, 0), pady=(4, 7))

    ctrl = ttk.Frame(win, padding=(16, 8))
    ctrl.grid(row=2, column=0, sticky='ew')
    ctrl.columnconfigure(0, weight=1)
    ttk.Label(ctrl, textvariable=counts, font=('Microsoft JhengHei UI', 11, 'bold')).grid(row=0, column=0, sticky='w')
    bar = ttk.Progressbar(ctrl, mode='determinate')
    bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(10, 3))
    ttk.Label(ctrl, textvariable=status).grid(row=2, column=0, sticky='w')

    log_frame = ttk.LabelFrame(win, text='處理紀錄', padding=8)
    log_frame.grid(row=3, column=0, sticky='nsew', padx=16, pady=8)
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    log = tk.Text(log_frame, height=12, wrap='word', state='disabled', font=('Consolas', 10))
    log.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(log_frame, command=log.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    log.config(yscrollcommand=scroll.set)

    bottom = ttk.Frame(win, padding=(16, 8, 16, 14))
    bottom.grid(row=4, column=0, sticky='ew')
    bottom.columnconfigure(0, weight=1)
    ttk.Label(bottom, text='注意：輸出路徑及 CSV 可能包含病患個資，請存於受控位置。', foreground='#965000').grid(row=0, column=0, sticky='w')

    def append(line):
        log.configure(state='normal')
        log.insert('end', str(line) + '\n')
        log.see('end')
        log.configure(state='disabled')

    def start():
        nonlocal active
        if active:
            return
        try:
            check_paths(source.get().strip(), dest.get().strip())
        except Exception as exc:
            messagebox.showerror('路徑錯誤', str(exc), parent=win)
            return
        active = True
        start_btn.config(state='disabled')
        counts.set('成功 0　｜　失敗 0　｜　待處理 0')
        status.set('掃描中…')
        bar.configure(mode='indeterminate')
        bar.start(10)
        append('========== 開始新批次 ==========')
        src, out = source.get(), dest.get()
        def work():
            try:
                result = run(src, out, lambda name, value: events.put((name, value)))
                events.put(('done', result))
            except Exception as exc:
                events.put(('fatal', (str(exc), traceback.format_exc())))
        threading.Thread(target=work, daemon=True).start()

    start_btn = ttk.Button(bottom, text='開始批次轉換', command=start)
    start_btn.grid(row=0, column=1, padx=(12, 0))

    def open_report(folder):
        try:
            os.startfile(folder)  # Windows Explorer
        except Exception:
            append('請手動開啟：' + folder)

    def poll():
        nonlocal active
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'log':
                    append(value)
                elif kind == 'scan':
                    found, skipped, series = value
                    status.set(f'掃描中：已檢查 {found:,} 檔案，找到 {series:,} 序列，略過 {skipped:,} 個檔案')
                elif kind == 'total':
                    bar.stop()
                    bar.configure(mode='determinate', maximum=max(1, value), value=0)
                    status.set(f'開始轉換 {value} 個序列…')
                elif kind == 'progress':
                    idx, total, ok, failed = value
                    bar['value'] = idx
                    counts.set(f'成功 {ok}　｜　失敗 {failed}　｜　待處理 {total - idx}')
                    status.set(f'進度：{idx}/{total} 個序列（{idx / total:.0%}）')
                elif kind == 'done':
                    active = False
                    start_btn.config(state='normal')
                    bar.stop()
                    ok, failed, skipped, report, examples = value
                    status.set(f'轉換完成：成功 {ok}，失敗 {failed}')
                    append('報告：' + report)
                    append('檔案對照表：' + str(Path(report).with_name('dicom_file_mapping.csv')))
                    if failed:
                        summary = '\n'.join(examples[:4])
                        messagebox.showwarning('批次完成，部分序列轉換失敗',
                            f'成功 {ok}，失敗 {failed}，略過 {skipped} 個檔案。\n\n'
                            f'部分錯誤：\n{summary}\n\n完整錯誤請查看：\n{report}', parent=win)
                    else:
                        messagebox.showinfo('批次轉換完成',
                            f'成功轉換 {ok} 個序列，失敗 0。\n'
                            f'略過 {skipped} 個非影像／不支援檔案。\n\n報告：\n{report}', parent=win)
                    open_report(str(Path(report).parent))
                elif kind == 'fatal':
                    active = False
                    bar.stop()
                    start_btn.config(state='normal')
                    status.set('批次中止')
                    err, trace = value
                    append(trace)
                    messagebox.showerror('發生錯誤', err, parent=win)
        except queue.Empty:
            pass
        win.after(120, poll)
    win.after(120, poll)
    win.mainloop()


if __name__ == '__main__':
    gui()
