//! Nonblocking Linux inotify adapter for the owned XDG desktop directory.
//! Call read_ready() only when the fd is readable in the existing calloop.
//! No sleeping, periodic timer, polling thread or extra dependency.
#![allow(dead_code)] // Runtime registration belongs to the Integration lane.

use std::{
    ffi::CString,
    fs,
    io,
    mem,
    os::{fd::{AsRawFd, FromRawFd, OwnedFd}, unix::{ffi::OsStrExt, fs::MetadataExt}},
    path::Path,
    time::{Duration, Instant},
};

use super::inventory::open_owned_directory;

pub const COALESCE: Duration = Duration::from_millis(125);
const BATCH_BYTES: usize = 16 * 1024;
const MAX_READS_PER_WAKE: usize = 32;
const ACTIVITY: u32 = libc::IN_CREATE | libc::IN_DELETE | libc::IN_MOVED_FROM
    | libc::IN_MOVED_TO | libc::IN_CLOSE_WRITE | libc::IN_ATTRIB;
const INVALIDATION: u32 = libc::IN_MOVE_SELF | libc::IN_DELETE_SELF
    | libc::IN_UNMOUNT | libc::IN_IGNORED;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refresh { Rescan, RebuildWatch }

#[derive(Debug, Default)]
struct State {
    pending: Option<Instant>,
    invalidated: bool,
    overflow: bool,
}

impl State {
    fn schedule(&mut self, now: Instant, immediate: bool) {
        let deadline = if immediate { now } else { now + COALESCE };
        self.pending = Some(self.pending.map_or(deadline, |old| old.min(deadline)));
    }

    fn observe(&mut self, mask: u32, now: Instant) {
        if mask & libc::IN_Q_OVERFLOW != 0 {
            self.overflow = true;
            self.schedule(now, true);
        }
        if mask & INVALIDATION != 0 {
            self.invalidated = true;
            self.schedule(now, true);
        } else if mask & ACTIVITY != 0 {
            self.schedule(now, false);
        }
    }

    fn due(&mut self, now: Instant) -> Option<Refresh> {
        if !self.pending.is_some_and(|deadline| deadline <= now) { return None; }
        self.pending = None;
        if self.invalidated { Some(Refresh::RebuildWatch) }
        else { Some(Refresh::Rescan) }
    }
}

#[derive(Debug)]
pub struct Watcher {
    fd: OwnedFd,
    watch: i32,
    state: State,
}

impl Watcher {
    /// No-follow validation occurs before and after installing the watch.
    /// Replacement or deletion is an error, never a watch on an arbitrary path.
    pub fn new(directory: &Path) -> io::Result<Self> {
        let pinned = open_owned_directory(directory)?;
        let original = pinned.metadata()?;
        let c_path = CString::new(directory.as_os_str().as_bytes())
            .map_err(|_| io::ErrorKind::InvalidInput)?;
        let raw = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
        if raw < 0 { return Err(io::Error::last_os_error()); }
        let fd = unsafe { OwnedFd::from_raw_fd(raw) };
        let mask = ACTIVITY | INVALIDATION | libc::IN_Q_OVERFLOW
            | libc::IN_ONLYDIR | libc::IN_DONT_FOLLOW;
        let wd = unsafe { libc::inotify_add_watch(fd.as_raw_fd(), c_path.as_ptr(), mask) };
        if wd < 0 { return Err(io::Error::last_os_error()); }
        let current = fs::symlink_metadata(directory)?;
        if !current.is_dir() || current.dev() != original.dev()
            || current.ino() != original.ino() {
            return Err(io::Error::new(io::ErrorKind::WouldBlock, "Desktop changed while installing watch"));
        }
        Ok(Self { fd, watch: wd, state: State::default() })
    }

    /// fd ownership remains with Watcher. Do not transfer it to an event loop.
    pub fn fd(&self) -> i32 { self.fd.as_raw_fd() }

    pub fn watch_descriptor(&self) -> i32 { self.watch }

    pub fn next_deadline(&self) -> Option<Instant> { self.state.pending }

    pub fn invalidated(&self) -> bool { self.state.invalidated }

    /// Clears the overflow diagnostic, not the requested full rescan.
    pub fn take_overflow(&mut self) -> bool { mem::take(&mut self.state.overflow) }

    /// Explicit Refresh is available when inotify is unavailable or the
    /// directory appears later. A caller can request a full inventory rebuild.
    pub fn request_refresh(&mut self, now: Instant) { self.state.schedule(now, true); }

    pub fn take_due(&mut self, now: Instant) -> Option<Refresh> { self.state.due(now) }

    /// Atomically replace the fd/watch only if installing the new one works.
    /// If the XDG root disappeared, retain the invalidated state for explicit
    /// retry after an external user action; never start a busy rearm loop.
    pub fn rearm(&mut self, directory: &Path) -> io::Result<()> {
        *self = Self::new(directory)?;
        Ok(())
    }

    pub fn read_ready(&mut self, now: Instant) -> io::Result<()> {
        let mut buffer = [0_u8; BATCH_BYTES];
        for _ in 0..MAX_READS_PER_WAKE {
            let count = unsafe { libc::read(self.fd.as_raw_fd(),
                buffer.as_mut_ptr().cast(), buffer.len()) };
            if count < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::WouldBlock { return Ok(()); }
                self.state.invalidated = true;
                self.state.schedule(now, true);
                return Err(error);
            }
            if count == 0 {
                self.state.invalidated = true;
                self.state.schedule(now, true);
                return Ok(());
            }
            let mut offset = 0;
            let size = count as usize;
            while offset < size {
                if size - offset < mem::size_of::<libc::inotify_event>() {
                    self.state.invalidated = true;
                    self.state.schedule(now, true);
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "Truncated inotify event"));
                }
                // Buffer is byte-aligned. read_unaligned avoids undefined behavior.
                let event: libc::inotify_event = unsafe {
                    std::ptr::read_unaligned(buffer[offset..].as_ptr().cast())
                };
                let len = mem::size_of::<libc::inotify_event>()
                    .checked_add(event.len as usize).ok_or(io::ErrorKind::InvalidData)?;
                if len > size - offset {
                    self.state.invalidated = true;
                    self.state.schedule(now, true);
                    return Err(io::Error::new(io::ErrorKind::InvalidData, "Invalid inotify event length"));
                }
                if event.wd == self.watch || event.mask & libc::IN_Q_OVERFLOW != 0 {
                    self.state.observe(event.mask, now);
                }
                offset += len;
            }
        }
        // Fairness: after a bounded drain, let calloop run other clients.
        // The still-readable fd will be delivered again by the reactor.
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{env, fs, path::PathBuf, time::{SystemTime, UNIX_EPOCH}};
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
            let path = env::temp_dir().join(format!("ricebowl-inotify-{}-{n}", std::process::id()));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[test]
    fn event_bursts_are_coalesced_without_extending_deadline() {
        let t = Instant::now();
        let mut state = State::default();
        state.observe(libc::IN_CREATE, t);
        state.observe(libc::IN_DELETE, t + Duration::from_millis(60));
        assert_eq!(state.pending, Some(t + COALESCE));
        assert_eq!(state.due(t + Duration::from_millis(124)), None);
        assert_eq!(state.due(t + COALESCE), Some(Refresh::Rescan));
        assert_eq!(state.due(t + COALESCE), None);
    }

    #[test]
    fn overflow_and_root_invalidation_have_distinct_recovery_paths() {
        let t = Instant::now();
        let mut s = State::default();
        s.observe(libc::IN_Q_OVERFLOW, t);
        assert!(s.overflow);
        assert_eq!(s.due(t), Some(Refresh::Rescan));
        s.observe(libc::IN_MOVE_SELF, t);
        assert_eq!(s.due(t), Some(Refresh::RebuildWatch));
    }

    #[test]
    fn live_create_rename_delete_and_owned_fd_cleanup() {
        let f = Fixture::new();
        let mut w = Watcher::new(&f.0).unwrap();
        let fd = w.fd();
        let t = Instant::now();
        fs::write(f.0.join("one"), b"data").unwrap();
        fs::rename(f.0.join("one"), f.0.join("two")).unwrap();
        fs::remove_file(f.0.join("two")).unwrap();
        w.read_ready(t).unwrap();
        assert_eq!(w.take_due(t + COALESCE), Some(Refresh::Rescan));
        assert!(!w.invalidated());
        drop(w);
        assert_eq!(unsafe { libc::fcntl(fd, libc::F_GETFD) }, -1);
    }

    #[test]
    fn removed_root_requires_rearm_no_polling_and_rejects_missing() {
        let f = Fixture::new();
        let dir = f.0.join("desktop");
        fs::create_dir(&dir).unwrap();
        let mut w = Watcher::new(&dir).unwrap();
        fs::remove_dir(&dir).unwrap();
        let t = Instant::now();
        w.read_ready(t).unwrap();
        assert_eq!(w.take_due(t), Some(Refresh::RebuildWatch));
        assert!(w.rearm(&dir).is_err());
        fs::create_dir(&dir).unwrap();
        w.rearm(&dir).unwrap();
        assert!(!w.invalidated());
        assert!(Watcher::new(&f.0.join("missing")).is_err());
    }
}
