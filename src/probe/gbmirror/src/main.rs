//! gbmirror: hidden-desktop live mirror + (stage 4) hardware recorder, host zero-interference.
//!
//! Two modes:
//!   capture-only:  gbmirror --desktop NAME --pid PID --out FILE.bmp [--frames N]
//!                  One-shot PrintWindow-stitch proof + host fg/cursor re-measurement.
//!   mirror UI:     gbmirror [--registry PATH] [--width N] [--fps N]
//!                  Host-visible window: session picker (left) + live hidden-desktop blit
//!                  (right). Reads the registry exported by hidden_sessions.py.
//!
//! Never SwitchDesktop; never kills a keep-alive stub. Capture runs on a SetThreadDesktop
//! worker; the host message loop only paints. Zero interference is re-measured, not assumed.

mod capture;
mod display;
mod record;
mod registry;

use capture::{capture_stitch, frame_stats, write_bmp, Frame};
use std::mem::zeroed;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{POINT, HANDLE};
use windows_sys::Win32::System::StationsAndDesktops::{CloseDesktop, OpenDesktopW, SetThreadDesktop};
use windows_sys::Win32::UI::WindowsAndMessaging::{GetCursorPos, GetForegroundWindow};

const GENERIC_ALL: u32 = 0x1000_0000;

fn utf16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn host_fg() -> isize {
    unsafe { GetForegroundWindow() as isize }
}

fn host_cursor() -> (i32, i32) {
    unsafe {
        let mut p: POINT = zeroed();
        GetCursorPos(&mut p);
        (p.x, p.y)
    }
}

fn dist(a: (i32, i32), b: (i32, i32)) -> i64 {
    let dx = (a.0 - b.0) as i64;
    let dy = (a.1 - b.1) as i64;
    ((dx * dx + dy * dy) as f64).sqrt() as i64
}

struct Args {
    desktop: Option<String>,
    pid: i64,
    out: String,
    frames: u32,
    registry: String,
    width: i32,
    fps: u32,
}

fn parse_args() -> Result<Args, String> {
    let mut a = Args {
        desktop: None,
        pid: 0,
        out: String::from("gbmirror.bmp"),
        frames: 5,
        registry: String::from("var/experiments/hidden_sessions.json"),
        width: 1000,
        fps: 30,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--desktop" => a.desktop = Some(it.next().ok_or("--desktop needs a value")?),
            "--pid" => a.pid = it.next().ok_or("--pid needs a value")?.parse().map_err(|_| "bad pid")?,
            "--out" => a.out = it.next().ok_or("--out needs a value")?,
            "--frames" => a.frames = it.next().ok_or("--frames needs a value")?.parse().map_err(|_| "bad frames")?,
            "--registry" => a.registry = it.next().ok_or("--registry needs a value")?,
            "--width" => a.width = it.next().ok_or("--width needs a value")?.parse().map_err(|_| "bad width")?,
            "--fps" => a.fps = it.next().ok_or("--fps needs a value")?.parse().map_err(|_| "bad fps")?,
            other => return Err(format!("unknown arg {other}")),
        }
    }
    Ok(a)
}

fn capture_mode(args: &Args) -> i32 {
    let desktop = args.desktop.clone().unwrap();
    let name = utf16(&desktop);
    let hdesk = unsafe { OpenDesktopW(name.as_ptr(), 0, 0, GENERIC_ALL) };
    if hdesk.is_null() {
        eprintln!("ABORT: OpenDesktopW({desktop}) failed (session not alive?)");
        return 2;
    }
    let fg0 = host_fg();
    let c0 = host_cursor();
    let (tx, rx) = mpsc::channel::<(Vec<(f64, usize, f64, usize, usize)>, Option<Frame>)>();
    let addr = hdesk as usize;
    let frames = args.frames;
    let th = thread::spawn(move || {
        let hd = addr as HANDLE;
        unsafe {
            if SetThreadDesktop(hd) == 0 {
                let _ = tx.send((vec![], None));
                return;
            }
        }
        let mut results = Vec::new();
        let mut last: Option<Frame> = None;
        for _ in 0..frames {
            let t = Instant::now();
            let f = unsafe { capture_stitch() };
            let ms = t.elapsed().as_secs_f64() * 1000.0;
            match f {
                Some(f) => {
                    let (nb, colors, total) = frame_stats(&f);
                    results.push((ms, f.windows.len(), nb, colors, total));
                    last = Some(f);
                }
                None => results.push((ms, 0, 0.0, 0, 0)),
            }
        }
        let _ = tx.send((results, last));
    });
    let mut fg_changed_during = false;
    let mut max_disp_during: i64 = 0;
    let mut got = None;
    loop {
        match rx.try_recv() {
            Ok(m) => {
                got = Some(m);
                break;
            }
            Err(mpsc::TryRecvError::Empty) => {
                if host_fg() != fg0 {
                    fg_changed_during = true;
                }
                let d = dist(c0, host_cursor());
                if d > max_disp_during {
                    max_disp_during = d;
                }
                thread::sleep(Duration::from_millis(5));
            }
            Err(mpsc::TryRecvError::Disconnected) => break,
        }
    }
    let _ = th.join();
    let fg1 = host_fg();
    let c1 = host_cursor();
    unsafe { CloseDesktop(hdesk) };
    let (results, last) = got.unwrap_or((vec![], None));
    let bmp_ok = match &last {
        Some(f) => write_bmp(&args.out, f).is_ok(),
        None => false,
    };
    let avg_ms = if results.is_empty() { 0.0 } else { results.iter().map(|r| r.0).sum::<f64>() / results.len() as f64 };
    let max_ms = results.iter().map(|r| r.0).fold(0.0f64, f64::max);
    let cursor_disp = dist(c0, c1);
    let zero = !fg_changed_during && fg0 == fg1 && cursor_disp == 0 && max_disp_during == 0;
    println!("{{");
    println!("  \"desktop\": \"{desktop}\", \"pid\": {}, \"frames\": {},", args.pid, args.frames);
    println!("  \"bmp_path\": \"{}\", \"bmp_ok\": {},", args.out.replace('\\', "\\\\"), bmp_ok);
    println!("  \"avg_capture_ms\": {avg_ms:.2}, \"max_capture_ms\": {max_ms:.2},");
    print!("  \"per_frame\": [");
    for (i, r) in results.iter().enumerate() {
        if i > 0 { print!(", "); }
        print!("{{\"ms\": {:.2}, \"windows\": {}, \"nonblack\": {:.4}, \"colors\": {}}}", r.0, r.1, r.2, r.3);
    }
    println!("],");
    if let Some(f) = &last {
        println!("  \"virtual_screen\": [{},{},{},{}],", f.virtual_screen.0, f.virtual_screen.1, f.virtual_screen.2, f.virtual_screen.3);
        println!("  \"last_window_count\": {},", f.windows.len());
    }
    println!("  \"host\": {{\"fg_before\": {fg0}, \"fg_after\": {fg1}, \"fg_changed\": {}, \"fg_changed_during\": {fg_changed_during},", fg0 != fg1);
    println!("           \"cursor_before\": [{},{}], \"cursor_after\": [{},{}], \"cursor_displacement\": {cursor_disp}, \"max_disp_during\": {max_disp_during}}},", c0.0, c0.1, c1.0, c1.1);
    println!("  \"zero_interference_observed\": {zero}");
    println!("}}");
    if bmp_ok { 0 } else { 1 }
}

fn main() {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ABORT: {e}");
            std::process::exit(2);
        }
    };
    if args.desktop.is_some() {
        std::process::exit(capture_mode(&args));
    }
    let sessions = registry::load(&args.registry);
    std::process::exit(display::run(sessions, args.width, args.fps));
}