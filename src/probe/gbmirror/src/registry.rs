//! Read the keep-alive session registry exported by hidden_sessions.py (serde_json Value,
//! no derive) and re-check process liveness so the picker shows current alive state.

use serde_json::Value;
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};

#[derive(Clone, Debug)]
#[allow(dead_code)] // hwnd/port carried for later stages (targeted capture / CDP)
pub struct Session {
    pub name: String,
    pub kind: String,
    pub desktop: String,
    pub pid: i64,
    pub alive: bool,
    pub hwnd: i64,
    pub port: Option<i64>,
}

pub fn pid_alive(pid: i64) -> bool {
    if pid <= 0 {
        return false;
    }
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snap.is_null() || snap as isize == -1 {
            return false;
        }
        let mut entry: PROCESSENTRY32W = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut found = false;
        if Process32FirstW(snap, &mut entry) != 0 {
            loop {
                if entry.th32ProcessID as i64 == pid {
                    found = true;
                    break;
                }
                if Process32NextW(snap, &mut entry) == 0 {
                    break;
                }
            }
        }
        windows_sys::Win32::Foundation::CloseHandle(snap);
        found
    }
}

pub fn load(path: &str) -> Vec<Session> {
    let txt = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(_) => return Vec::new(),
    };
    let v: Value = serde_json::from_str(&txt).unwrap_or(Value::Null);
    let arr = match v.as_array() {
        Some(a) => a.clone(),
        None => return Vec::new(),
    };
    arr.iter()
        .map(|o| {
            let pid = o["pid"].as_i64().unwrap_or(0);
            Session {
                name: o["name"].as_str().unwrap_or("").to_string(),
                kind: o["kind"].as_str().unwrap_or("").to_string(),
                desktop: o["desktop"].as_str().unwrap_or("").to_string(),
                pid,
                alive: pid_alive(pid),
                hwnd: o["hwnd"].as_i64().unwrap_or(0),
                port: o["port"].as_i64(),
            }
        })
        .collect()
}