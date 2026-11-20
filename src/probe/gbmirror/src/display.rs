//! Host-visible mirror window: owner-drawn session picker (left) + GDI StretchDIBits blit of
//! the in-memory hidden-desktop frame (right). No PNG round-trips, no tkinter poll. A capture
//! worker thread (SetThreadDesktop on the hidden desktop) fills a shared frame buffer; the
//! host message loop paints it. Switching sessions stops the old worker, CloseDesktop, and
//! attaches the new desktop. Read-only on the hidden desktop; host fg/cursor untouched.

use crate::capture::{capture_stitch, crop, Frame};
use crate::record;
use crate::registry::Session;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{HINSTANCE, HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, EndPaint, GetStockObject, InvalidateRect, SetBkMode, SetTextColor, StretchDIBits,
    TextOutW, UpdateWindow, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, BLACK_BRUSH, DIB_RGB_COLORS,
    DEFAULT_GUI_FONT, PAINTSTRUCT, SRCCOPY, TRANSPARENT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::StationsAndDesktops::{CloseDesktop, OpenDesktopW, SetThreadDesktop};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, KillTimer, LoadCursorW,
    PostQuitMessage, RegisterClassExW, SetTimer, SetWindowLongPtrW, GetWindowLongPtrW, ShowWindow,
    TranslateMessage, CREATESTRUCTW, CW_USEDEFAULT, GWLP_USERDATA, IDC_ARROW, MSG, SW_SHOW,
    WM_CREATE, WM_DESTROY, WM_LBUTTONDOWN, WM_PAINT, WM_TIMER, WNDCLASSEXW, WS_OVERLAPPEDWINDOW,
    WS_VISIBLE,
};

const GENERIC_ALL: u32 = 0x1000_0000;
const PICKER_W: i32 = 230;
const LINE_H: i32 = 30;
const MIRROR_H: i32 = 430;
const TIMER_PAINT: usize = 1;

pub struct Shared {
    pub frame: Option<Frame>,
    pub seq: u64,
    pub avg_ms: f64,
    pub rec_on: bool,
    pub rec_path: String,
    pub rec_info: String,
}

pub struct AppState {
    pub sessions: Vec<Session>,
    pub current: usize,
    pub shared: Arc<Mutex<Shared>>,
    pub stop: Arc<AtomicBool>,
    pub worker: Option<JoinHandle<()>>,
    pub hdesk: usize,
    pub mirror_w: i32,
    pub interval_ms: u32,
}

fn utf16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
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
                let f = unsafe { capture_stitch() };
                let ms = t.elapsed().as_secs_f64() * 1000.0;
                ema = if ema == 0.0 { ms } else { ema * 0.8 + ms * 0.2 };
                if let Some(f) = f {
                    let bbox = content_bbox(&f);
                    let (cw, ch, cbgra) = crop(&f, bbox);
                    let (rec_on, rec_path) = {
                        let s = shared.lock().unwrap();
                        (s.rec_on, s.rec_path.clone())
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
                    let mut s = shared.lock().unwrap();
                    s.frame = Some(f);
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

fn content_bbox(f: &Frame) -> (i32, i32, i32, i32) {
    let (vx, vy, vw, vh) = f.virtual_screen;
    if f.windows.is_empty() {
        return (0, 0, vw, vh);
    }
    let mut x0 = i32::MAX;
    let mut y0 = i32::MAX;
    let mut x1 = i32::MIN;
    let mut y1 = i32::MIN;
    for w in &f.windows {
        let (x, y, w_, h_) = w.rect;
        x0 = x0.min(x - vx);
        y0 = y0.min(y - vy);
        x1 = x1.max(x - vx + w_);
        y1 = y1.max(y - vy + h_);
    }
    (x0.max(0), y0.max(0), (x1 - x0).min(vw), (y1 - y0).min(vh))
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
            }
            0
        }
        WM_PAINT => {
            let mut ps: PAINTSTRUCT = std::mem::zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let font = GetStockObject(DEFAULT_GUI_FONT);
            let old = windows_sys::Win32::Graphics::Gdi::SelectObject(hdc, font);
            SetBkMode(hdc, TRANSPARENT as i32);
            if let Some(st) = state(hwnd) {
                // picker panel
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
                    SetTextColor(hdc, col);
                    let t = utf16(&label);
                    TextOutW(hdc, 8, 8 + i as i32 * LINE_H, t.as_ptr(), t.len() as i32 - 1);
                }
                // REC toggle line
                let (rec_on, rec_info) = {
                    let s = st.shared.lock().unwrap();
                    (s.rec_on, s.rec_info.clone())
                };
                let rec_label = format!(
                    "{} REC  {}",
                    if rec_on { ">" } else { " " },
                    if rec_on { "[on]" } else { "[off]" }
                );
                SetTextColor(hdc, if rec_on { 0x004040FF } else { 0x00E0E0E0 });
                let rt = utf16(&rec_label);
                TextOutW(hdc, 8, 8 + st.sessions.len() as i32 * LINE_H, rt.as_ptr(), rt.len() as i32 - 1);
                // status lines
                let (seq, avg) = {
                    let s = st.shared.lock().unwrap();
                    (s.seq, s.avg_ms)
                };
                let fps = if avg > 0.0 { 1000.0 / avg } else { 0.0 };
                let cur = st.sessions.get(st.current);
                let status = format!(
                    "capture {:.1} fps\nframes {}\ndesktop {}\nhost_fg {}\n{}",
                    fps,
                    seq,
                    cur.map(|c| c.desktop.as_str()).unwrap_or("-"),
                    windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow() as isize,
                    rec_info
                );
                SetTextColor(hdc, 0x00909090);
                for (li, line) in status.lines().enumerate() {
                    let t = utf16(line);
                    TextOutW(
                        hdc,
                        8,
                        8 + (st.sessions.len() as i32 + 1) * LINE_H + 16 + li as i32 * 18,
                        t.as_ptr(),
                        t.len() as i32 - 1,
                    );
                }
                // mirror blit (content-cropped, scaled)
                let s = st.shared.lock().unwrap();
                if let Some(f) = &s.frame {
                    let (sx, sy, sw, sh) = content_bbox(f);
                    if sw > 0 && sh > 0 {
                        let mut bmi: BITMAPINFO = std::mem::zeroed();
                        bmi.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
                        bmi.bmiHeader.biWidth = f.width;
                        bmi.bmiHeader.biHeight = -f.height;
                        bmi.bmiHeader.biPlanes = 1;
                        bmi.bmiHeader.biBitCount = 32;
                        bmi.bmiHeader.biCompression = BI_RGB;
                        let dw = st.mirror_w;
                        let dh = ((sh as i64 * dw as i64) / sw as i64).max(1) as i32;
                        StretchDIBits(
                            hdc,
                            PICKER_W, 0, dw, dh.min(MIRROR_H),
                            sx, sy, sw, sh,
                            f.bgra.as_ptr() as *const _,
                            &bmi,
                            DIB_RGB_COLORS,
                            SRCCOPY,
                        );
                    }
                }
            }
            windows_sys::Win32::Graphics::Gdi::SelectObject(hdc, old);
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

pub fn run(sessions: Vec<Session>, mirror_w: i32, fps: u32) -> i32 {
    if sessions.is_empty() {
        eprintln!("ABORT: registry has no sessions; run hidden_sessions.py export first");
        return 2;
    }
    let interval_ms = (1000 / fps.max(1)).max(1);
    let state = Box::new(AppState {
        sessions,
        current: 0,
        shared: Arc::new(Mutex::new(Shared {
            frame: None,
            seq: 0,
            avg_ms: 0.0,
            rec_on: false,
            rec_path: String::from("var/experiments/gbmirror_rec.mp4"),
            rec_info: String::from("rec off"),
        })),
        stop: Arc::new(AtomicBool::new(false)),
        worker: None,
        hdesk: 0,
        mirror_w,
        interval_ms,
    });
    let ptr = Box::into_raw(state);

    unsafe {
        let hinst: HINSTANCE = GetModuleHandleW(std::ptr::null());
        let class = utf16("GBMirrorWnd");
        let title = utf16("GUIBridge hidden-desktop mirror (Rust, host zero-interference)");
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            style: 0,
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
            CW_USEDEFAULT, CW_USEDEFAULT,
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
        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        let _ = Box::from_raw(ptr);
        msg.wParam as i32
    }
}