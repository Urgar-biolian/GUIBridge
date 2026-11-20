//! Hardware-preferred H.264 recording of mirror frames via Media Foundation SinkWriter.
//!
//! MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS lets MF pick a hardware H.264 MFT when present
//! (falls back to the software encoder otherwise). Frames arrive as top-down BGRA; MF input
//! type is RGB32. COM is initialized MTA on the calling (capture worker) thread. No ffmpeg
//! dependency — Media Foundation is built into Windows.

use windows::core::PCWSTR;
use windows::Win32::Media::MediaFoundation::{
    MFCreateAttributes, MFCreateMediaType, MFCreateMemoryBuffer, MFCreateSample,
    MFCreateSinkWriterFromURL, MFShutdown, MFStartup, IMFAttributes, IMFSinkWriter,
    MF_MT_AVG_BITRATE, MF_MT_DEFAULT_STRIDE, MF_MT_FRAME_RATE, MF_MT_FRAME_SIZE,
    MF_MT_INTERLACE_MODE, MF_MT_MAJOR_TYPE, MF_MT_PIXEL_ASPECT_RATIO, MF_MT_SUBTYPE,
    MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, MF_VERSION,
    MFMediaType_Video, MFVideoFormat_H264, MFVideoFormat_RGB32,
};
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};

pub struct Recorder {
    writer: IMFSinkWriter,
    stream: u32,
    width: u32,
    height: u32,
    fps: u32,
    pub frames: u64,
}

fn utf16(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

impl Recorder {
    pub fn new(path: &str, w: u32, h: u32, fps: u32) -> windows::core::Result<Self> {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            MFStartup(MF_VERSION, 0)?;
            let mut attrs: Option<IMFAttributes> = None;
            MFCreateAttributes(&mut attrs, 2)?;
            let attrs = attrs.unwrap();
            attrs.SetUINT32(&MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1)?;
            let url = utf16(path);
            let writer = MFCreateSinkWriterFromURL(PCWSTR(url.as_ptr()), None, &attrs)?;

            let out = MFCreateMediaType()?;
            out.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            out.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_H264)?;
            out.SetUINT32(&MF_MT_AVG_BITRATE, 8_000_000)?;
            out.SetUINT32(&MF_MT_INTERLACE_MODE, 2)?; // progressive
            out.SetUINT64(&MF_MT_FRAME_SIZE, ((w as u64) << 32) | h as u64)?;
            out.SetUINT64(&MF_MT_FRAME_RATE, ((fps as u64) << 32) | 1)?;
            out.SetUINT64(&MF_MT_PIXEL_ASPECT_RATIO, (1u64 << 32) | 1)?;
            let stream = writer.AddStream(&out)?;

            let inp = MFCreateMediaType()?;
            inp.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
            inp.SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_RGB32)?;
            inp.SetUINT32(&MF_MT_INTERLACE_MODE, 2)?; // progressive
            inp.SetUINT64(&MF_MT_FRAME_SIZE, ((w as u64) << 32) | h as u64)?;
            inp.SetUINT64(&MF_MT_FRAME_RATE, ((fps as u64) << 32) | 1)?;
            inp.SetUINT64(&MF_MT_PIXEL_ASPECT_RATIO, (1u64 << 32) | 1)?;
            inp.SetUINT32(&MF_MT_DEFAULT_STRIDE, w * 4)?;
            writer.SetInputMediaType(stream, &inp, None)?;
            writer.BeginWriting()?;
            Ok(Self { writer, stream, width: w, height: h, fps, frames: 0 })
        }
    }

    pub fn dims(&self) -> (u32, u32) {
        (self.width, self.height)
    }

    pub fn write(&mut self, bgra: &[u8]) -> windows::core::Result<()> {
        unsafe {
            let cb = self.width * self.height * 4;
            let buf = MFCreateMemoryBuffer(cb)?;
            let mut ptr: *mut u8 = std::ptr::null_mut();
            let mut max = 0u32;
            let mut cur = 0u32;
            buf.Lock(&mut ptr, Some(&mut max), Some(&mut cur))?;
            std::ptr::copy_nonoverlapping(bgra.as_ptr(), ptr, cb as usize);
            buf.Unlock()?;
            buf.SetCurrentLength(cb)?;
            let sample = MFCreateSample()?;
            sample.AddBuffer(&buf)?;
            let dur = 10_000_000i64 / self.fps as i64;
            sample.SetSampleTime(self.frames as i64 * dur)?;
            sample.SetSampleDuration(dur)?;
            self.writer.WriteSample(self.stream, &sample)?;
            self.frames += 1;
            Ok(())
        }
    }

    pub fn finish(self) -> windows::core::Result<u64> {
        unsafe {
            self.writer.Finalize()?;
            MFShutdown()?;
            Ok(self.frames)
        }
    }
}