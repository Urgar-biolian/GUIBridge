//! Hidden-desktop full-screen capture by PrintWindow stitching (E14 method B), in Rust.
//!
//! MUST run on a thread whose desktop is the hidden desktop (SetThreadDesktop). A hidden
//! desktop is not the active input desktop, so it has no DWM-composed surface: whole-screen
//! BitBlt is black. Instead we PrintWindow(PW_RENDERFULLCONTENT) every visible top-level
//! window into a virtual-screen-sized canvas at its real screen rect, largest first
//! (approximate z-order). Read-only: cannot change the host foreground or cursor.
//!
//! Frames stay in memory as top-down BGRA (zero PNG round-trips). A BMP writer is provided
//! only for one-off proof artifacts.

use std::mem::{size_of, zeroed};
use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM, RECT, TRUE};
use windows_sys::Win32::Graphics::Gdi::{
    BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC, GetDIBits,
    PatBlt, ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, BLACKNESS,
    DIB_RGB_COLORS, SRCCOPY,
};
use windows_sys::Win32::Storage::Xps::PrintWindow;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetSystemMetrics, GetWindowRect, IsWindow, IsWindowVisible, PW_RENDERFULLCONTENT,
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
};

const NULL: HWND = std::ptr::null_mut();

#[derive(Clone)]
pub struct WinInfo {
    pub hwnd: isize,
    pub rect: (i32, i32, i32, i32),
    pub printwindow: bool,
    pub blit: bool,
}

pub struct Frame {
    pub width: i32,
    pub height: i32,
    pub bgra: Vec<u8>, // top-down BGRA, len = width*height*4
    pub virtual_screen: (i32, i32, i32, i32), // content-bbox origin+size in absolute screen coords
    pub windows: Vec<WinInfo>,
}

unsafe extern "system" fn enum_cb(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let vec = &mut *(lparam as *mut Vec<HWND>);
    if IsWindowVisible(hwnd) != 0 {
        let mut r: RECT = zeroed();
        if GetWindowRect(hwnd, &mut r) != 0 {
            if r.right - r.left > 0 && r.bottom - r.top > 0 {
                vec.push(hwnd);
            }
        }
    }
    TRUE
}

/// Capture the hidden desktop's visible-window union into an in-memory top-down BGRA frame.
/// Worker-side. The canvas is the content bbox, NOT the whole virtual screen: on multi-monitor
/// hosts the physical virtual screen is huge (measured 5760x2000) and a full-screen canvas cost
/// ~112ms/frame in alloc+GetDIBits alone; the union bbox cuts that to the actual content size.
pub unsafe fn capture_stitch() -> Option<Frame> {
    capture_stitch_focus(None)
}

/// Same as capture_stitch, but the canvas is the focus window's rect (the session's main
/// window) instead of the union of all visible windows: stray helper windows on other
/// monitors otherwise inflate the union (measured 3151x1802 vs 1609x1370 main-only).
/// Falls back to the union when the focus hwnd is dead or off-screen.
pub unsafe fn capture_stitch_focus(focus: Option<HWND>) -> Option<Frame> {
    let vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
    let vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
    let vw = GetSystemMetrics(SM_CXVIRTUALSCREEN).max(1);
    let vh = GetSystemMetrics(SM_CYVIRTUALSCREEN).max(1);

    let mut hwnds: Vec<HWND> = Vec::new();
    EnumWindows(Some(enum_cb), &mut hwnds as *mut Vec<HWND> as LPARAM);

    let mut wins: Vec<(HWND, RECT, i64)> = Vec::new();
    for h in hwnds {
        let mut r: RECT = zeroed();
        if GetWindowRect(h, &mut r) != 0 {
            let area = (r.right - r.left) as i64 * (r.bottom - r.top) as i64;
            wins.push((h, r, area));
        }
    }
    if wins.is_empty() {
        return None;
    }
    wins.sort_by(|a, b| b.2.cmp(&a.2)); // largest first

    let mut focus_rect: Option<RECT> = None;
    if let Some(fh) = focus {
        if IsWindow(fh) != 0 {
            let mut r: RECT = zeroed();
            if GetWindowRect(fh, &mut r) != 0 && r.right > r.left && r.bottom > r.top {
                focus_rect = Some(r);
            }
        }
    }
    let (ux0, uy0, ux1, uy1) = match focus_rect {
        Some(r) => (r.left.max(vx), r.top.max(vy), r.right.min(vx + vw), r.bottom.min(vy + vh)),
        None => (
            wins.iter().map(|(_, r, _)| r.left).min().unwrap().max(vx),
            wins.iter().map(|(_, r, _)| r.top).min().unwrap().max(vy),
            wins.iter().map(|(_, r, _)| r.right).max().unwrap().min(vx + vw),
            wins.iter().map(|(_, r, _)| r.bottom).max().unwrap().min(vy + vh),
        ),
    };
    let cw = (ux1 - ux0).max(1);
    let ch = (uy1 - uy0).max(1);

    let screen_dc = GetDC(NULL);
    let mem_dc = CreateCompatibleDC(screen_dc);
    let bmp = CreateCompatibleBitmap(screen_dc, cw, ch);
    let old = SelectObject(mem_dc, bmp);
    PatBlt(mem_dc, 0, 0, cw, ch, BLACKNESS); // hidden desktop paints no wallpaper

    let mut placed: Vec<WinInfo> = Vec::new();
    for (h, r, _) in &wins {
        let x = r.left;
        let y = r.top;
        let w = (r.right - r.left).max(1);
        let hh = (r.bottom - r.top).max(1);
        let hwnd_dc = GetDC(*h);
        let tmp_dc = CreateCompatibleDC(hwnd_dc);
        let tbmp = CreateCompatibleBitmap(hwnd_dc, w, hh);
        let told = SelectObject(tmp_dc, tbmp);
        let pw = PrintWindow(*h, tmp_dc, PW_RENDERFULLCONTENT) != 0;
        let blit = BitBlt(mem_dc, x - ux0, y - uy0, w, hh, tmp_dc, 0, 0, SRCCOPY) != 0;
        SelectObject(tmp_dc, told);
        DeleteObject(tbmp);
        DeleteDC(tmp_dc);
        ReleaseDC(*h, hwnd_dc);
        placed.push(WinInfo {
            hwnd: *h as isize,
            rect: (x, y, w, hh),
            printwindow: pw,
            blit,
        });
    }

    let mut bmi: BITMAPINFO = zeroed();
    bmi.bmiHeader.biSize = size_of::<BITMAPINFOHEADER>() as u32;
    bmi.bmiHeader.biWidth = cw;
    bmi.bmiHeader.biHeight = -ch; // top-down
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;
    let mut buf = vec![0u8; (cw as usize) * (ch as usize) * 4];
    let got = GetDIBits(
        mem_dc,
        bmp,
        0,
        ch as u32,
        buf.as_mut_ptr() as *mut _,
        &mut bmi,
        DIB_RGB_COLORS,
    );
    SelectObject(mem_dc, old);
    DeleteObject(bmp);
    DeleteDC(mem_dc);
    ReleaseDC(NULL, screen_dc);
    if got == 0 {
        return None;
    }
    Some(Frame {
        width: cw,
        height: ch,
        bgra: buf,
        virtual_screen: (ux0, uy0, cw, ch),
        windows: placed,
    })
}

/// Coarse non-blank metrics on a stride sample (full-image loop would be slow).
pub fn frame_stats(f: &Frame) -> (f64, usize, usize) {
    let n = (f.width as usize) * (f.height as usize);
    let stride = (n / 20000).max(1);
    let mut nb = 0usize;
    let mut total = 0usize;
    let mut colors = std::collections::HashSet::new();
    let mut i = 0usize;
    while i < n {
        let b = f.bgra[i * 4];
        let g = f.bgra[i * 4 + 1];
        let r = f.bgra[i * 4 + 2];
        total += 1;
        if b != 0 || g != 0 || r != 0 {
            nb += 1;
        }
        if colors.len() < 4096 {
            colors.insert(((r as u32) << 16) | ((g as u32) << 8) | b as u32);
        }
        i += stride;
    }
    (nb as f64 / total.max(1) as f64, colors.len(), total)
}

/// Encode a top-down BGRA buffer as a bottom-up 32bpp BMP in memory.
pub fn bmp_bytes(w: u32, h: u32, bgra: &[u8]) -> Vec<u8> {
    let w = w as usize;
    let h = h as usize;
    let row = w * 4;
    let data_size = (row * h) as u32;
    let mut out = Vec::with_capacity(54 + data_size as usize);
    // BITMAPFILEHEADER (14 bytes)
    out.extend_from_slice(&0x4D42u16.to_le_bytes()); // 'BM'
    out.extend_from_slice(&(14 + 40 + data_size).to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out.extend_from_slice(&54u32.to_le_bytes());
    // BITMAPINFOHEADER (40 bytes), bottom-up
    out.extend_from_slice(&40u32.to_le_bytes());
    out.extend_from_slice(&(w as i32).to_le_bytes());
    out.extend_from_slice(&(h as i32).to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes());
    out.extend_from_slice(&32u16.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes()); // BI_RGB
    out.extend_from_slice(&data_size.to_le_bytes());
    out.extend_from_slice(&0i32.to_le_bytes());
    out.extend_from_slice(&0i32.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes());
    // pixel rows reversed (top-down buffer -> bottom-up file)
    for y in (0..h).rev() {
        out.extend_from_slice(&bgra[y * row..(y + 1) * row]);
    }
    out
}

/// Write a top-down BGRA frame as a bottom-up 32bpp BMP (proof artifact only).
pub fn write_bmp(path: &str, f: &Frame) -> std::io::Result<()> {
    std::fs::write(path, bmp_bytes(f.width as u32, f.height as u32, &f.bgra))
}

/// Union of the captured windows' rects in buffer coords (drops empty black margins).
pub fn content_bbox(f: &Frame) -> (i32, i32, i32, i32) {
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
    let x0 = x0.max(0);
    let y0 = y0.max(0);
    let x1 = x1.min(vw).max(x0 + 1);
    let y1 = y1.min(vh).max(y0 + 1);
    (x0, y0, x1 - x0, y1 - y0)
}

/// Resample a source rect of a frame into a new top-down BGRA buffer: box-average when
/// downscaling (clean text), nearest-neighbor when upscaling (pixel-sharp). Runs on the capture
/// worker: HALFTONE StretchDIBits on the UI thread cost seconds per multi-MP paint and froze
/// the message loop ("not responding") during zoom/pan.
pub fn resample(f: &Frame, sx: i32, sy: i32, sw: i32, sh: i32, dw: i32, dh: i32) -> Vec<u8> {
    let dw = dw.max(1) as usize;
    let dh = dh.max(1) as usize;
    let mut out = vec![0u8; dw * dh * 4];
    let fw = f.width as usize;
    let fh = f.height as usize;
    let sx = (sx.max(0) as usize).min(fw);
    let sy = (sy.max(0) as usize).min(fh);
    let sw = (sw.max(1) as usize).min(fw - sx);
    let sh = (sh.max(1) as usize).min(fh - sy);
    if sw == 0 || sh == 0 {
        return out;
    }
    let src = &f.bgra;
    if dw <= sw && dh <= sh {
        for dy in 0..dh {
            let y0 = sy + dy * sh / dh;
            let y1 = (sy + (dy + 1) * sh / dh).max(y0 + 1).min(fh);
            for dx in 0..dw {
                let x0 = sx + dx * sw / dw;
                let x1 = (sx + (dx + 1) * sw / dw).max(x0 + 1).min(fw);
                let (mut b, mut g, mut r, mut n) = (0u64, 0u64, 0u64, 0u64);
                for yy in y0..y1 {
                    let row = yy * fw;
                    for xx in x0..x1 {
                        let i = (row + xx) * 4;
                        b += src[i] as u64;
                        g += src[i + 1] as u64;
                        r += src[i + 2] as u64;
                        n += 1;
                    }
                }
                let o = (dy * dw + dx) * 4;
                out[o] = (b / n) as u8;
                out[o + 1] = (g / n) as u8;
                out[o + 2] = (r / n) as u8;
                out[o + 3] = 255;
            }
        }
    } else {
        for dy in 0..dh {
            let row = (sy + dy * sh / dh) * fw;
            for dx in 0..dw {
                let i = (row + sx + dx * sw / dw) * 4;
                let o = (dy * dw + dx) * 4;
                out[o..o + 4].copy_from_slice(&src[i..i + 4]);
            }
        }
    }
    out
}

/// Crop a top-down BGRA frame to a content bbox (x, y, w, h) in buffer coords.
pub fn crop(f: &Frame, bbox: (i32, i32, i32, i32)) -> (u32, u32, Vec<u8>) {
    let (x, y, w, h) = bbox;
    let fw = f.width as usize;
    let fh = f.height as usize;
    let x = (x.max(0) as usize).min(fw);
    let y = (y.max(0) as usize).min(fh);
    let w = (w.max(1) as usize).min(fw - x);
    let h = (h.max(1) as usize).min(fh - y);
    if w == 0 || h == 0 {
        return (0, 0, Vec::new());
    }
    let stride = fw * 4;
    let mut out = vec![0u8; w * h * 4];
    for row in 0..h {
        let src = (y + row) * stride + x * 4;
        let dst = row * w * 4;
        out[dst..dst + w * 4].copy_from_slice(&f.bgra[src..src + w * 4]);
    }
    (w as u32, h as u32, out)
}