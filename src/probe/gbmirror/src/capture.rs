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
    EnumWindows, GetSystemMetrics, GetWindowRect, IsWindowVisible, PW_RENDERFULLCONTENT,
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
    pub virtual_screen: (i32, i32, i32, i32),
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

/// Capture the whole hidden desktop into an in-memory top-down BGRA frame. Worker-side.
pub unsafe fn capture_stitch() -> Option<Frame> {
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
    wins.sort_by(|a, b| b.2.cmp(&a.2)); // largest first

    let screen_dc = GetDC(NULL);
    let mem_dc = CreateCompatibleDC(screen_dc);
    let bmp = CreateCompatibleBitmap(screen_dc, vw, vh);
    let old = SelectObject(mem_dc, bmp);
    PatBlt(mem_dc, 0, 0, vw, vh, BLACKNESS); // hidden desktop paints no wallpaper

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
        let blit = BitBlt(mem_dc, x - vx, y - vy, w, hh, tmp_dc, 0, 0, SRCCOPY) != 0;
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
    bmi.bmiHeader.biWidth = vw;
    bmi.bmiHeader.biHeight = -vh; // top-down
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;
    let mut buf = vec![0u8; (vw as usize) * (vh as usize) * 4];
    let got = GetDIBits(
        mem_dc,
        bmp,
        0,
        vh as u32,
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
        width: vw,
        height: vh,
        bgra: buf,
        virtual_screen: (vx, vy, vw, vh),
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

/// Write a top-down BGRA frame as a bottom-up 32bpp BMP (proof artifact only).
pub fn write_bmp(path: &str, f: &Frame) -> std::io::Result<()> {
    use std::io::Write;
    let w = f.width as usize;
    let h = f.height as usize;
    let row = w * 4;
    let data_size = (row * h) as u32;
    let mut out = std::fs::File::create(path)?;
    // BITMAPFILEHEADER (14 bytes)
    out.write_all(&0x4D42u16.to_le_bytes())?; // 'BM'
    out.write_all(&(14 + 40 + data_size).to_le_bytes())?;
    out.write_all(&0u16.to_le_bytes())?;
    out.write_all(&0u16.to_le_bytes())?;
    out.write_all(&54u32.to_le_bytes())?;
    // BITMAPINFOHEADER (40 bytes), bottom-up
    out.write_all(&40u32.to_le_bytes())?;
    out.write_all(&(w as i32).to_le_bytes())?;
    out.write_all(&(h as i32).to_le_bytes())?;
    out.write_all(&1u16.to_le_bytes())?;
    out.write_all(&32u16.to_le_bytes())?;
    out.write_all(&0u32.to_le_bytes())?; // BI_RGB
    out.write_all(&data_size.to_le_bytes())?;
    out.write_all(&0i32.to_le_bytes())?;
    out.write_all(&0i32.to_le_bytes())?;
    out.write_all(&0u32.to_le_bytes())?;
    out.write_all(&0u32.to_le_bytes())?;
    // pixel rows reversed (top-down buffer -> bottom-up file)
    for y in (0..h).rev() {
        out.write_all(&f.bgra[y * row..(y + 1) * row])?;
    }
    Ok(())
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