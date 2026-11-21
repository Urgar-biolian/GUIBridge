//! Pipe-stream mode: continuous hidden-desktop frames for the web dashboard (MJPEG source).
//!
//! stdout: `u32 LE payload length` + bottom-up 32bpp BMP (content-cropped, worker-scaled to
//!         `--width`). stderr: one JSON meta line per second carrying fps, capture cost and a
//!         ROLLING 2s host-interference window (foreground switches / cursor displacement).
//!
//! Nothing is written to disk. Capture stays on a SetThreadDesktop worker; the host thread only
//! samples fg/cursor and pipes bytes, so the host is never SwitchDesktop'd. A rolling window is
//! used instead of a since-start boolean because a long-lived viewer legitimately moves the
//! mouse / switches apps: those are external input, not interference caused by the capture.
//! `--frames 0` streams until the pipe breaks or the process is terminated.

use crate::capture::{bmp_bytes, capture_stitch, content_bbox, crop, resample, Frame};
use crate::{dist, host_cursor, host_fg};
use std::collections::VecDeque;
use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::StationsAndDesktops::{CloseDesktop, OpenDesktopW, SetThreadDesktop};

const GENERIC_ALL: u32 = 0x1000_0000;
const WINDOW: Duration = Duration::from_secs(2);

pub struct StreamArgs {
    pub desktop: String,
    pub pid: i64,
    pub width: i32,
    pub fps: u32,
    pub frames: u32,
}

fn utf16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// Foreground switches + max cursor step inside the rolling sample window. These count the
/// VIEWER's own mouse/app use too: they are host activity, not attributed capture interference.
fn window_counters(samples: &VecDeque<(Instant, isize, (i32, i32))>) -> (u32, i64) {
    let mut switches = 0u32;
    let mut maxd = 0i64;
    let mut prev: Option<(isize, (i32, i32))> = None;
    for (_, fg, c) in samples.iter() {
        if let Some((pfg, pc)) = prev {
            if *fg != pfg {
                switches += 1;
            }
            maxd = maxd.max(dist(pc, *c));
        }
        prev = Some((*fg, *c));
    }
    (switches, maxd)
}

pub fn run(a: &StreamArgs) -> i32 {
    let name = utf16(&a.desktop);
    let hdesk = unsafe { OpenDesktopW(name.as_ptr(), 0, 0, GENERIC_ALL) };
    if hdesk.is_null() {
        eprintln!("ABORT: OpenDesktopW({}) failed (session not alive?)", a.desktop);
        return 2;
    }
    let stop = Arc::new(AtomicBool::new(false));
    let worker_stop = stop.clone();
    let (tx, rx) = mpsc::sync_channel::<(Vec<u8>, u32, u32, f64)>(2);
    let addr = hdesk as usize;
    let target_w = a.width.max(16);
    let interval = (1000 / a.fps.max(1)).max(1);
    let limit = a.frames;

    let th = thread::spawn(move || {
        unsafe {
            if SetThreadDesktop(addr as HANDLE) == 0 {
                return;
            }
        }
        let mut n = 0u32;
        while !worker_stop.load(Ordering::SeqCst) {
            let t = Instant::now();
            let f = unsafe { capture_stitch() };
            let ms = t.elapsed().as_secs_f64() * 1000.0;
            if let Some(f) = f {
                let (cw, ch, cbgra) = crop(&f, content_bbox(&f));
                let cw = cw.max(1);
                let ch = ch.max(1);
                let dw = (cw as i32).min(target_w).max(1);
                let dh = ((ch as f64) * (dw as f64 / cw as f64)).round().max(1.0) as i32;
                let scaled = if dw == cw as i32 && dh == ch as i32 {
                    cbgra
                } else {
                    let tmp = Frame {
                        width: cw as i32,
                        height: ch as i32,
                        bgra: cbgra,
                        virtual_screen: f.virtual_screen,
                        windows: Vec::new(),
                    };
                    resample(&tmp, 0, 0, cw as i32, ch as i32, dw, dh)
                };
                let bmp = bmp_bytes(dw as u32, dh as u32, &scaled);
                if tx.send((bmp, dw as u32, dh as u32, ms)).is_err() {
                    break; // viewer went away
                }
            }
            n += 1;
            if limit > 0 && n >= limit {
                break;
            }
            let elapsed = t.elapsed().as_millis() as u32;
            if elapsed < interval {
                thread::sleep(Duration::from_millis((interval - elapsed) as u64));
            }
        }
    });

    let mut out = std::io::stdout().lock();
    let mut samples: VecDeque<(Instant, isize, (i32, i32))> = VecDeque::new();
    let mut seq: u64 = 0;
    let mut meta_frames: u64 = 0;
    let mut ema = 0.0f64;
    let (mut last_w, mut last_h) = (0u32, 0u32);
    let mut last_meta = Instant::now();
    let mut pipe_broken = false;

    loop {
        match rx.recv_timeout(Duration::from_millis(5)) {
            Ok((bmp, w, h, ms)) => {
                ema = if ema == 0.0 { ms } else { ema * 0.8 + ms * 0.2 };
                last_w = w;
                last_h = h;
                let len = bmp.len() as u32;
                let wrote = out
                    .write_all(&len.to_le_bytes())
                    .and_then(|_| out.write_all(&bmp))
                    .and_then(|_| out.flush());
                if wrote.is_err() {
                    pipe_broken = true;
                    break;
                }
                seq += 1;
                meta_frames += 1;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
        let now = Instant::now();
        samples.push_back((now, host_fg(), host_cursor()));
        while let Some(front) = samples.front() {
            if now.duration_since(front.0) > WINDOW {
                samples.pop_front();
            } else {
                break;
            }
        }
        if last_meta.elapsed() >= Duration::from_secs(1) {
            let el = last_meta.elapsed().as_secs_f64().max(0.001);
            let (switches, maxd) = window_counters(&samples);
            let meta = serde_json::json!({
                "desktop": a.desktop, "pid": a.pid, "seq": seq,
                "fps": meta_frames as f64 / el,
                "avg_capture_ms": ema, "width": last_w, "height": last_h,
                "rolling_window_s": WINDOW.as_secs_f64(),
                "samples": samples.len(),
                "fg_switches": switches, "cursor_disp": maxd,
                "counters_unattributed": true,
                "pipe_broken": pipe_broken,
            });
            eprintln!("{meta}");
            last_meta = Instant::now();
            meta_frames = 0;
        }
    }

    stop.store(true, Ordering::SeqCst);
    drop(rx);
    drop(out);
    let _ = th.join();
    unsafe { CloseDesktop(hdesk) };
    let (switches, maxd) = window_counters(&samples);
    let final_meta = serde_json::json!({
        "desktop": a.desktop, "pid": a.pid, "seq": seq, "final": true,
        "avg_capture_ms": ema, "width": last_w, "height": last_h,
        "rolling_window_s": WINDOW.as_secs_f64(), "samples": samples.len(),
        "fg_switches": switches, "cursor_disp": maxd,
        "counters_unattributed": true,
        "pipe_broken": pipe_broken,
    });
    eprintln!("{final_meta}");
    if seq == 0 {
        eprintln!("ABORT: no frame captured (SetThreadDesktop or capture failed)");
        return 2;
    }
    0
}