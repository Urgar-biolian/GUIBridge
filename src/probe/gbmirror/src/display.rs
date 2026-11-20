//! Host-visible mirror window: owner-drawn session picker (left) + 1:1 blit of a
//! worker-resampled hidden-desktop view (right). The capture worker (SetThreadDesktop on the
//! hidden desktop) captures, resamples to the current view geometry (zoom/pan) and publishes a
//! display-ready buffer; the host message loop only fills + blits, so it never blocks on
//! resampling (HALFTONE on the UI thread previously saturated the loop => "not responding").
//! Switching sessions stops the old worker, CloseDesktop, and attaches the new desktop.
//! Read-only on the hidden desktop; host fg/cursor untouched.

use crate::capture::{capture_stitch_focus, content_bbox, crop, resample, Frame};
use crate::record;
use crate::registry::Session;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{HINSTANCE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject,
    DrawTextW, EndPaint, FillRect, GetStockObject, InvalidateRect, ScreenToClient, SelectObject,
    SetBkMode, SetTextColor, StretchDIBits, UpdateWindow, BITMAPINFO, BITMAPINFOHEADER, BI_RGB,
    BLACK_BRUSH, DIB_RGB_COLORS, DEFAULT_GUI_FONT, DT_END_ELLIPSIS, DT_NOPREFIX, DT_SINGLELINE,
    DT_VCENTER, PAINTSTRUCT, SRCCOPY, TRANSPARENT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::StationsAndDesktops::{CloseDesktop, OpenDesktopW, SetThreadDesktop};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{ReleaseCapture, SetCapture};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetClientRect, GetMessageW, KillTimer,
    LoadCursorW, PostMessageW, PostQuitMessage, RegisterClassExW, SetTimer, SetWindowLongPtrW,
    GetWindowLongPtrW, ShowWindow, TranslateMessage, CREATESTRUCTW, CS_DBLCLKS, GWLP_USERDATA,
    IDC_ARROW, MSG, SC_MAXIMIZE, SW_SHOW, WM_CREATE, WM_DESTROY, WM_ERASEBKGND, WM_LBUTTONDBLCLK,
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_PAINT, WM_SIZE, WM_SYSCOMMAND,
    WM_TIMER, WNDCLASSEXW, WS_OVERLAPPEDWINDOW, WS_VISIBLE,
};

const GENERIC_ALL: u32 = 0x1000_0000;
const PICKER_W: i32 = 230;
const LINE_H: i32 = 30;
const MIRROR_H: i32 = 900;
const TIMER_PAINT: usize = 1;

/// Display-ready view buffer produced by the worker at the current zoom/pan/size.
pub struct ViewFrame {
    pub bgra: Vec<u8>,
    pub w: i32,
    pub h: i32,
    pub dx: i32,
    pub dy: i32,
}

pub struct Shared {
    pub frame: Option<Frame>,
    pub view: Option<ViewFrame>,
    pub seq: u64,
    pub avg_ms: f64,
    pub rec_on: bool,
    pub rec_path: String,
    pub rec_info: String,
    pub mw: i32,
    pub mh: i32,
    pub zoom: f64,
    pub cx: f64,
    pub cy: f64,
}

pub struct AppState {
    pub sessions: Vec<Session>,
    pub current: usize,
    pub shared: Arc<Mutex<Shared>>,
    pub stop: Arc<AtomicBool>,
    pub worker: Option<JoinHandle<()>>,
    pub hdesk: usize,
    pub last_seq: u64,
    pub dragging: bool,
    pub last_mouse: (i32, i32),
    pub interval_ms: u32,
    pub status_path: String,
    pub status_tick: u32,
}

/// Export mirror/rec state for the read-only localhost dashboard (gbdash). Stale ts
/// (>5s) means the mirror is not running; the dashboard never writes back.
fn write_status(st: &AppState) {
    let s = st.shared.lock().unwrap();
    let cur = st.sessions.get(st.current);
    let fps = if s.avg_ms > 0.0 { 1000.0 / s.avg_ms } else { 0.0 };
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    let v = serde_json::json!({
        "pid": std::process::id(),
        "ts": ts,
        "current": cur.map(|c| c.name.clone()).unwrap_or_default(),
        "desktop": cur.map(|c| c.desktop.clone()).unwrap_or_default(),
        "fps": fps,
        "seq": s.seq,
        "zoom": s.zoom,
        "rec_on": s.rec_on,
        "rec_info": s.rec_info,
        "rec_path": s.rec_path,
    });
    let _ = std::fs::write(&st.status_path, v.to_string());
}

fn utf16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// View geometry in frame coords: (scale, src_x, src_y, src_w, src_h, center_x, center_y).
/// zoom=1 is fit-within (centered); zoom>1 shows a smaller pannable source rect.
fn view_geom(
    mw: i32,
    mh: i32,
    zoom: f64,
    cx: f64,
    cy: f64,
    f: &Frame,
) -> (f64, f64, f64, f64, f64, f64, f64) {
    let (bx, by, bw, bh) = content_bbox(f);
    let mw = mw as f64;
    let mh = mh as f64;
    let s0 = (mw / bw as f64).min(mh / bh as f64);
    let s = s0 * zoom;
    let vw = (mw / s).min(bw as f64);
    let vh = (mh / s).min(bh as f64);
    let (cx, cy) = if zoom <= 1.0 {
        (bw as f64 / 2.0, bh as f64 / 2.0)
    } else {
        (
            cx.clamp(vw / 2.0, bw as f64 - vw / 2.0),
            cy.clamp(vh / 2.0, bh as f64 - vh / 2.0),
        )
    };
    (
        s,
        bx as f64 + cx - vw / 2.0,
        by as f64 + cy - vh / 2.0,
        vw,
        vh,
        cx,
        cy,
    )
}

impl AppState {
    fn stop_worker(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(w) = self.worker.take() {
            let _ = w.join();
        }
        if self.hdesk != 0 {
            unsafe { CloseDesktop(self.hdesk as *mut _) };
            self.hdesk = 0;
        }
    }

    fn start_worker(&mut self, desktop: &str) {
        let name = utf16(desktop);
        let hdesk = unsafe { OpenDesktopW(name.as_ptr(), 0, 0, GENERIC_ALL) };
        if hdesk.is_null() {
            return;
        }
        self.hdesk = hdesk as usize;
        self.stop = Arc::new(AtomicBool::new(false));
        let stop = self.stop.clone();
        let shared = self.shared.clone();
        let addr = self.hdesk;
        let interval = self.interval_ms;
        let focus_hwnd = self.sessions[self.current].hwnd;
        self.worker = Some(std::thread::spawn(move || {
            unsafe {
                if SetThreadDesktop(addr as *mut _) == 0 {
                    return;
                }
            }
            let mut ema = 0.0f64;
            let mut rec: Option<record::Recorder> = None;
            while !stop.load(Ordering::SeqCst) {
                let t = Instant::now();
                let f = unsafe {
                    capture_stitch_focus(if focus_hwnd > 0 {
                        Some(focus_hwnd as HWND)
                    } else {
                        None
                    })
                };
                let ms = t.elapsed().as_secs_f64() * 1000.0;
                ema = if ema == 0.0 { ms } else { ema * 0.8 + ms * 0.2 };
                if let Some(f) = f {
                    let bbox = content_bbox(&f);
                    let (cw, ch, cbgra) = crop(&f, bbox);
                    let (mw, mh, zoom, cx, cy, rec_on, rec_path) = {
                        let s = shared.lock().unwrap();
                        (s.mw, s.mh, s.zoom, s.cx, s.cy, s.rec_on, s.rec_path.clone())
                    };
                    if rec_on {
                        let need_new = match &rec {
                            Some(r) => r.dims() != (cw, ch),
                            None => true,
                        };
                        if need_new {
                            if let Some(r) = rec.take() {
                                let _ = r.finish();
                            }
                            let rfps = (1000.0 / ema.max(1.0)).round().max(1.0) as u32;
                            rec = record::Recorder::new(&rec_path, cw, ch, rfps).ok();
                        }
                        let info = match rec.as_mut() {
                            Some(r) => match r.write(&cbgra) {
                                Ok(()) => format!("rec {} frames", r.frames),
                                Err(e) => format!("rec write err: {e}"),
                            },
                            None => String::from("rec init failed"),
                        };
                        let mut s = shared.lock().unwrap();
                        s.rec_info = info;
                    } else if let Some(r) = rec.take() {
                        let info = match r.finish() {
                            Ok(n) => format!("saved {n} frames"),
                            Err(e) => format!("rec finalize err: {e}"),
                        };
                        let mut s = shared.lock().unwrap();
                        s.rec_info = info;
                    }
                    // resample here (worker), never on the UI thread
                    let (sc, sx, sy, vw, vh, ccx, ccy) = view_geom(mw, mh, zoom, cx, cy, &f);
                    let dw = (vw * sc).max(1.0) as i32;
                    let dh = (vh * sc).max(1.0) as i32;
                    let vbgra = resample(&f, sx as i32, sy as i32, vw as i32, vh as i32, dw, dh);
                    let view = ViewFrame {
                        bgra: vbgra,
                        w: dw,
                        h: dh,
                        dx: (mw - dw).max(0) / 2,
                        dy: (mh - dh).max(0) / 2,
                    };
                    let mut s = shared.lock().unwrap();
                    s.frame = Some(f);
                    s.view = Some(view);
                    s.cx = ccx;
                    s.cy = ccy;
                    s.seq += 1;
                    s.avg_ms = ema;
                }
                let elapsed = t.elapsed().as_millis() as u32;
                if elapsed < interval {
                    std::thread::sleep(Duration::from_millis((interval - elapsed) as u64));
                }
            }
            if let Some(r) = rec.take() {
                let _ = r.finish();
            }
        }));
    }

    fn switch(&mut self, idx: usize) {
        if idx >= self.sessions.len() || idx == self.current && self.hdesk != 0 {
            return;
        }
        self.stop_worker();
        self.current = idx;
        {
            let mut s = self.shared.lock().unwrap();
            s.zoom = 1.0;
            s.cx = 0.0;
            s.cy = 0.0;
            s.view = None;
        }
        let desktop = self.sessions[idx].desktop.clone();
        self.start_worker(&desktop);
    }
}

unsafe fn state(hwnd: HWND) -> Option<&'static mut AppState> {
    let p = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut AppState;
    if p.is_null() {
        None
    } else {
        Some(&mut *p)
    }
}


unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    match msg {
        WM_CREATE => {
            let cs = &*(lparam as *const CREATESTRUCTW);
            let p = cs.lpCreateParams as *mut AppState;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, p as isize);
            if let Some(st) = state(hwnd) {
                let desktop = st.sessions[st.current].desktop.clone();
                st.start_worker(&desktop);
            }
            SetTimer(hwnd, TIMER_PAINT, 16, None);
            0
        }
        WM_TIMER => {
            if let Some(st) = state(hwnd) {
                let seq = st.shared.lock().unwrap().seq;
                if seq != st.last_seq {
                    st.last_seq = seq;
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                }
                st.status_tick += 1;
                if st.status_tick >= 1000 / st.interval_ms.max(1) {
                    st.status_tick = 0;
                    write_status(st);
                }
            }
            0
        }
        WM_SIZE => {
            let cw = (lparam & 0xFFFF) as u16 as i32;
            let ch = ((lparam >> 16) & 0xFFFF) as u16 as i32;
            if let Some(st) = state(hwnd) {
                let mut s = st.shared.lock().unwrap();
                s.mw = (cw - PICKER_W).max(1);
                s.mh = ch.max(1);
            }
            InvalidateRect(hwnd, std::ptr::null(), 0);
            0
        }
        WM_LBUTTONDOWN => {
            let x = (lparam & 0xFFFF) as u16 as i32;
            let y = ((lparam >> 16) & 0xFFFF) as u16 as i32;
            if x < PICKER_W {
                let idx = (y / LINE_H) as usize;
                if let Some(st) = state(hwnd) {
                    if idx < st.sessions.len() {
                        st.switch(idx);
                    } else if idx == st.sessions.len() {
                        let mut s = st.shared.lock().unwrap();
                        s.rec_on = !s.rec_on;
                        if s.rec_on {
                            s.rec_info = String::from("rec starting");
                        }
                    }
                }
                InvalidateRect(hwnd, std::ptr::null(), 0);
            } else if let Some(st) = state(hwnd) {
                st.dragging = true;
                st.last_mouse = (x, y);
                SetCapture(hwnd);
            }
            0
        }
        WM_MOUSEMOVE => {
            let x = (lparam & 0xFFFF) as u16 as i32;
            let y = ((lparam >> 16) & 0xFFFF) as u16 as i32;
            if let Some(st) = state(hwnd) {
                if st.dragging {
                    let dx = x - st.last_mouse.0;
                    let dy = y - st.last_mouse.1;
                    st.last_mouse = (x, y);
                    let mut s = st.shared.lock().unwrap();
                    if let Some(f) = &s.frame {
                        let (sc, _, _, _, _, _, _) = view_geom(s.mw, s.mh, s.zoom, s.cx, s.cy, f);
                        s.cx -= dx as f64 / sc;
                        s.cy -= dy as f64 / sc;
                    }
                    drop(s);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                }
            }
            0
        }
        WM_LBUTTONUP => {
            if let Some(st) = state(hwnd) {
                if st.dragging {
                    st.dragging = false;
                    ReleaseCapture();
                }
            }
            0
        }
        WM_LBUTTONDBLCLK => {
            let x = (lparam & 0xFFFF) as u16 as i32;
            if x >= PICKER_W {
                if let Some(st) = state(hwnd) {
                    st.shared.lock().unwrap().zoom = 1.0;
                }
                InvalidateRect(hwnd, std::ptr::null(), 0);
            }
            0
        }
        WM_MOUSEWHEEL => {
            let delta = ((wparam >> 16) & 0xFFFF) as u16 as i16 as i32;
            let mut pt = POINT {
                x: (lparam & 0xFFFF) as u16 as i32,
                y: ((lparam >> 16) & 0xFFFF) as u16 as i32,
            };
            ScreenToClient(hwnd, &mut pt);
            if pt.x >= PICKER_W {
                if let Some(st) = state(hwnd) {
                    let mut s = st.shared.lock().unwrap();
                    let geom = s
                        .frame
                        .as_ref()
                        .map(|f| view_geom(s.mw, s.mh, s.zoom, s.cx, s.cy, f));
                    if let Some((sc, sx, sy, vw, vh, _, _)) = geom {
                        let mx = (pt.x - PICKER_W) as f64;
                        let my = pt.y as f64;
                        let dx = (s.mw as f64 - vw * sc) / 2.0;
                        let dy = (s.mh as f64 - vh * sc) / 2.0;
                        // source point under the cursor stays anchored while zooming
                        let px = sx + (mx - dx) / sc;
                        let py = sy + (my - dy) / sc;
                        let newzoom = (s.zoom * if delta > 0 { 1.25 } else { 0.8 }).clamp(1.0, 8.0);
                        let geom1 = s
                            .frame
                            .as_ref()
                            .map(|f| view_geom(s.mw, s.mh, newzoom, s.cx, s.cy, f));
                        if let Some((sc1, _, _, vw1, vh1, _, _)) = geom1 {
                            let dx1 = (s.mw as f64 - vw1 * sc1) / 2.0;
                            let dy1 = (s.mh as f64 - vh1 * sc1) / 2.0;
                            s.zoom = newzoom;
                            s.cx = px - (mx - dx1) / sc1 + vw1 / 2.0;
                            s.cy = py - (my - dy1) / sc1 + vh1 / 2.0;
                        }
                    }
                    drop(s);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                }
            }
            0
        }
        WM_ERASEBKGND => 1, // paint fills the whole client itself; erasing here causes drag flicker
        WM_PAINT => {
            let mut ps: PAINTSTRUCT = std::mem::zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let mut rc: RECT = std::mem::zeroed();
            GetClientRect(hwnd, &mut rc);
            let cw = rc.right;
            let ch = rc.bottom;
            if cw > 0 && ch > 0 {
                // Double buffer: fill + draw everything offscreen, one BitBlt to screen.
                // Without the full fill, transparent-mode text accumulates over old glyphs.
                let mem = CreateCompatibleDC(hdc);
                let bmp = CreateCompatibleBitmap(hdc, cw, ch);
                let oldbm = SelectObject(mem, bmp);
                FillRect(mem, &rc, GetStockObject(BLACK_BRUSH));
                let oldf = SelectObject(mem, GetStockObject(DEFAULT_GUI_FONT));
                SetBkMode(mem, TRANSPARENT as i32);
                if let Some(st) = state(hwnd) {
                    let (zoom, seq, avg, rec_on, rec_info) = {
                        let s = st.shared.lock().unwrap();
                        // mirror: 1:1 blit of the worker-resampled view (no UI-thread resampling)
                        if let Some(v) = &s.view {
                            let mut bmi: BITMAPINFO = std::mem::zeroed();
                            bmi.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
                            bmi.bmiHeader.biWidth = v.w;
                            bmi.bmiHeader.biHeight = -v.h;
                            bmi.bmiHeader.biPlanes = 1;
                            bmi.bmiHeader.biBitCount = 32;
                            bmi.bmiHeader.biCompression = BI_RGB;
                            StretchDIBits(
                                mem,
                                PICKER_W + v.dx, v.dy, v.w, v.h,
                                0, 0, v.w, v.h,
                                v.bgra.as_ptr() as *const _,
                                &bmi,
                                DIB_RGB_COLORS,
                                SRCCOPY,
                            );
                        }
                        (s.zoom, s.seq, s.avg_ms, s.rec_on, s.rec_info.clone())
                    };
                    // picker column: ellipsized to column width so long lines never
                    // spill into the mirror area
                    let text_rect = |y: i32, h: i32| RECT {
                        left: 8,
                        top: y,
                        right: PICKER_W - 8,
                        bottom: y + h,
                    };
                    let fmt = DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX;
                    for (i, s) in st.sessions.iter().enumerate() {
                        let label = format!(
                            "{} {}  {}",
                            if i == st.current { ">" } else { " " },
                            s.name,
                            if s.alive { "[alive]" } else { "[dead]" }
                        );
                        let col = if i == st.current {
                            0x00FFD080
                        } else if s.alive {
                            0x00E0E0E0
                        } else {
                            0x00606060
                        };
                        SetTextColor(mem, col);
                        let t = utf16(&label);
                        let mut r = text_rect(8 + i as i32 * LINE_H, LINE_H);
                        DrawTextW(mem, t.as_ptr(), -1, &mut r, fmt);
                    }
                    // REC toggle line
                    let rec_label = format!(
                        "{} REC  {}",
                        if rec_on { ">" } else { " " },
                        if rec_on { "[on]" } else { "[off]" }
                    );
                    SetTextColor(mem, if rec_on { 0x004040FF } else { 0x00E0E0E0 });
                    let rt = utf16(&rec_label);
                    let mut r = text_rect(8 + st.sessions.len() as i32 * LINE_H, LINE_H);
                    DrawTextW(mem, rt.as_ptr(), -1, &mut r, fmt);
                    // status lines
                    let fps = if avg > 0.0 { 1000.0 / avg } else { 0.0 };
                    let cur = st.sessions.get(st.current);
                    let status = format!(
                        "capture {:.1} fps\nframes {}\ndesktop {}\nhost_fg {}\nzoom {:.2}x wheel/drag\n{}",
                        fps,
                        seq,
                        cur.map(|c| c.desktop.as_str()).unwrap_or("-"),
                        windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow() as isize,
                        zoom,
                        rec_info
                    );
                    SetTextColor(mem, 0x00909090);
                    for (li, line) in status.lines().enumerate() {
                        let t = utf16(line);
                        let mut r = text_rect(
                            8 + (st.sessions.len() as i32 + 1) * LINE_H + 16 + li as i32 * 18,
                            18,
                        );
                        DrawTextW(mem, t.as_ptr(), -1, &mut r, fmt);
                    }
                }
                SelectObject(mem, oldf);
                BitBlt(hdc, 0, 0, cw, ch, mem, 0, 0, SRCCOPY);
                SelectObject(mem, oldbm);
                DeleteObject(bmp);
                DeleteDC(mem);
            }
            EndPaint(hwnd, &ps);
            0
        }
        WM_DESTROY => {
            if let Some(st) = state(hwnd) {
                st.stop_worker();
            }
            KillTimer(hwnd, TIMER_PAINT);
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

pub fn run(sessions: Vec<Session>, mirror_w: i32, fps: u32, status_path: String) -> i32 {
    if sessions.is_empty() {
        eprintln!("ABORT: registry has no sessions; run hidden_sessions.py export first");
        return 2;
    }
    let interval_ms = (1000 / fps.max(1)).max(1);
    let app = Box::new(AppState {
        sessions,
        current: 0,
        shared: Arc::new(Mutex::new(Shared {
            frame: None,
            view: None,
            seq: 0,
            avg_ms: 0.0,
            rec_on: false,
            rec_path: String::from("var/experiments/gbmirror_rec.mp4"),
            rec_info: String::from("rec off"),
            mw: mirror_w,
            mh: MIRROR_H,
            zoom: 1.0,
            cx: 0.0,
            cy: 0.0,
        })),
        stop: Arc::new(AtomicBool::new(false)),
        worker: None,
        hdesk: 0,
        last_seq: 0,
        dragging: false,
        last_mouse: (0, 0),
        interval_ms,
        status_path,
        status_tick: 0,
    });
    let ptr = Box::into_raw(app);

    unsafe {
        let hinst: HINSTANCE = GetModuleHandleW(std::ptr::null());
        let class = utf16("GBMirrorWnd");
        let title = utf16("GUIBridge hidden-desktop mirror (Rust, host zero-interference)");
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            style: CS_DBLCLKS,
            lpfnWndProc: Some(wndproc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: hinst,
            hIcon: std::ptr::null_mut(),
            hCursor: LoadCursorW(std::ptr::null_mut(), IDC_ARROW),
            hbrBackground: GetStockObject(BLACK_BRUSH),
            lpszMenuName: std::ptr::null(),
            lpszClassName: class.as_ptr(),
            hIconSm: std::ptr::null_mut(),
        };
        RegisterClassExW(&wc);
        let hwnd = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            80, 80,
            PICKER_W + mirror_w + 16,
            MIRROR_H + 40,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            hinst,
            ptr as *const _,
        );
        if hwnd.is_null() {
            eprintln!("ABORT: CreateWindowExW failed");
            let _ = Box::from_raw(ptr);
            return 2;
        }
        ShowWindow(hwnd, SW_SHOW);
        UpdateWindow(hwnd);
        // ShowWindow(SW_SHOWMAXIMIZED) right after creation did not stick (measured showCmd=1);
        // posting SC_MAXIMIZE lets the message loop perform the maximize reliably.
        PostMessageW(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE as WPARAM, 0);
        if let Some(st) = state(hwnd) {
            write_status(st);
        }
        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        let _ = Box::from_raw(ptr);
        msg.wParam as i32
    }
}