//! Nonblocking Linux inotify source for the real user Desktop.
//!
//! No worker thread, shell command, global watch, or per-frame polling.
//! The caller owns the event-loop registration; this module only drains the
//! watched directory's events and reports if the snapshot became stale.
use std::{
    ffi::CString,
    io,
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::ffi::OsStrExt,
    },
    path::Path,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Change {
    None,
    Refresh,
    WatchLost,
}

pub struct Watch {
    fd: OwnedFd,
}

impl Watch {
    pub fn open(directory: &Path) -> io::Result<Self> {
        let directory = CString::new(directory.as_os_str().as_bytes())
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "NUL in Desktop path"))?;
        let raw = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
        if raw < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: inotify_init1 returned a fresh descriptor owned by this Watch.
        let fd = unsafe { OwnedFd::from_raw_fd(raw) };
        let mask = libc::IN_CREATE
            | libc::IN_DELETE
            | libc::IN_MOVED_FROM
            | libc::IN_MOVED_TO
            | libc::IN_ATTRIB
            | libc::IN_CLOSE_WRITE
            | libc::IN_DELETE_SELF
            | libc::IN_MOVE_SELF
            | libc::IN_UNMOUNT;
        if unsafe { libc::inotify_add_watch(fd.as_raw_fd(), directory.as_ptr(), mask) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { fd })
    }

    /// A duplicate descriptor wakes calloop while this owner drains events.
    /// Both handles are closed automatically if registration is removed.
    pub fn try_clone_fd(&self) -> io::Result<OwnedFd> {
        self.fd.try_clone()
    }

    /// Drain all queued events to EAGAIN, otherwise a level-triggered source
    /// would spin. The caller coalesces Refresh requests before rescanning.
    pub fn drain(&self) -> io::Result<Change> {
        let mut refresh = false;
        let mut buffer = [0u8; 8192];
        let header = std::mem::size_of::<libc::inotify_event>();
        loop {
            let size = unsafe {
                libc::read(
                    self.fd.as_raw_fd(),
                    buffer.as_mut_ptr().cast::<libc::c_void>(),
                    buffer.len(),
                )
            };
            if size < 0 {
                let error = io::Error::last_os_error();
                return match error.kind() {
                    io::ErrorKind::Interrupted => continue,
                    io::ErrorKind::WouldBlock => Ok(if refresh {
                        Change::Refresh
                    } else {
                        Change::None
                    }),
                    _ => Err(error),
                };
            }
            if size == 0 {
                return Ok(Change::WatchLost);
            }
            let size = size as usize;
            let mut offset = 0usize;
            while offset < size {
                if size - offset < header {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "Short inotify event"));
                }
                // SAFETY: bounds checked above; inotify buffers need not be aligned.
                let event = unsafe {
                    std::ptr::read_unaligned(
                        buffer.as_ptr().add(offset).cast::<libc::inotify_event>(),
                    )
                };
                let event_size = header + event.len as usize;
                if event_size > size - offset {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "Truncated inotify name"));
                }
                offset += event_size;
                if event.mask
                    & (libc::IN_IGNORED
                        | libc::IN_DELETE_SELF
                        | libc::IN_MOVE_SELF
                        | libc::IN_UNMOUNT)
                    != 0
                {
                    return Ok(Change::WatchLost);
                }
                // An overflow requires a complete bounded rescan.
                if event.mask & libc::IN_Q_OVERFLOW != 0 {
                    refresh = true;
                }
                if event.mask
                    & (libc::IN_CREATE
                        | libc::IN_DELETE
                        | libc::IN_MOVED_FROM
                        | libc::IN_MOVED_TO
                        | libc::IN_ATTRIB
                        | libc::IN_CLOSE_WRITE)
                    != 0
                {
                    refresh = true;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        os::unix::ffi::OsStringExt,
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temporary_directory() -> std::path::PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "ricebowl-inotify-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        root
    }

    #[test]
    fn create_rename_delete_and_non_utf8_names_request_one_refresh() {
        let root = temporary_directory();
        let watch = Watch::open(&root).unwrap();
        let name = std::ffi::OsString::from_vec(b"file-\xff".to_vec());
        fs::write(root.join(&name), b"data").unwrap();
        fs::rename(root.join(&name), root.join("renamed")).unwrap();
        fs::remove_file(root.join("renamed")).unwrap();
        assert_eq!(watch.drain().unwrap(), Change::Refresh);
        assert_eq!(watch.drain().unwrap(), Change::None);
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn removed_desktop_directory_invalidates_watch() {
        let root = temporary_directory();
        let watch = Watch::open(&root).unwrap();
        fs::remove_dir(root).unwrap();
        assert_eq!(watch.drain().unwrap(), Change::WatchLost);
    }

    #[test]
    fn invalid_directory_and_embedded_nul_fail_closed() {
        assert!(Watch::open(Path::new("/a/directory/that/does/not/exist")).is_err());
        assert!(Watch::open(Path::new("/tmp/bad\0name")).is_err());
    }
}
