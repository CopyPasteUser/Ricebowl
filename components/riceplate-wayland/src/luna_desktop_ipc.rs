//! Opt-in Luna desktop root-menu bridge. The compositor already owns the
//! background right-click: do not create a transparent fullscreen layer.
//! Only fixed, allowlisted commands cross the local owner-private datagram socket.
use std::{env,fs,io,os::unix::{fs::{FileTypeExt,MetadataExt,PermissionsExt},net::UnixDatagram},
          path::{Path,PathBuf}};

#[derive(Clone,Copy,Debug,Eq,PartialEq)]
pub enum Request { Arrange, NewFolder, Refresh, Properties, ShowDesktop, Run, Explorer }

impl Request {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "arrange" => Some(Self::Arrange),
            "new-folder" => Some(Self::NewFolder),
            "refresh" => Some(Self::Refresh),
            "properties" => Some(Self::Properties),
            "show-desktop" => Some(Self::ShowDesktop),
            "run" => Some(Self::Run),
            "explorer" => Some(Self::Explorer),
            _ => None,
        }
    }
    fn wire(self) -> &'static [u8] {
        match self {
            Self::Arrange => b"arrange",
            Self::NewFolder => b"new-folder",
            Self::Refresh => b"refresh",
            Self::Properties => b"properties",
            Self::ShowDesktop => b"show-desktop",
            Self::Run => b"run",
            Self::Explorer => b"explorer",
        }
    }
    pub fn decode(raw: &[u8]) -> Option<Self> {
        std::str::from_utf8(raw).ok().and_then(Self::parse)
    }
}

pub struct Listener {
    socket: UnixDatagram,
    path: PathBuf,
    inode: u64,
}
impl Listener {
    pub fn try_clone(&self) -> io::Result<UnixDatagram> {
        self.socket.try_clone()
    }
}

fn socket_path() -> io::Result<PathBuf> {
    let dir = env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from)
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound,"No runtime directory"))?;
    if !dir.is_absolute() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput,"Non-absolute runtime directory"));
    }
    let stat = fs::symlink_metadata(&dir)?;
    if !stat.is_dir() || stat.uid() != unsafe { libc::geteuid() }
        || stat.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,"Unsafe runtime directory"));
    }
    Ok(dir.join("riceplate-luna-desktop.sock"))
}

pub fn bind() -> io::Result<Listener> {
    let path = socket_path()?;
    if let Ok(stat) = fs::symlink_metadata(&path) {
        if !stat.file_type().is_socket() || stat.uid() != unsafe { libc::geteuid() } {
            return Err(io::Error::new(io::ErrorKind::AlreadyExists,"Unsafe socket occupant"));
        }
        let probe = UnixDatagram::unbound()?;
        match probe.connect(&path) {
            Ok(()) => return Err(io::Error::new(io::ErrorKind::AddrInUse,"Luna already running")),
            Err(error) if error.kind() == io::ErrorKind::ConnectionRefused =>
                fs::remove_file(&path)?,
            Err(error) => return Err(error),
        }
    }
    let socket = UnixDatagram::bind(&path)?;
    fs::set_permissions(&path,fs::Permissions::from_mode(0o600))?;
    socket.set_nonblocking(true)?;
    let inode = fs::symlink_metadata(&path)?.ino();
    Ok(Listener {socket,path,inode})
}

impl Drop for Listener {
    fn drop(&mut self) {
        if fs::symlink_metadata(&self.path).is_ok_and(|meta|
            meta.ino() == self.inode && meta.file_type().is_socket()) {
            let _ = fs::remove_file(&self.path);
        }
    }
}

/// Invoke a single allowlisted command in an already-running Luna session.
/// This command does not start Wayland or launch any process of its own.
pub fn send(request: Request) -> io::Result<()> {
    let path = socket_path()?;
    let meta = fs::symlink_metadata(&path)?;
    if !meta.file_type().is_socket() || meta.uid() != unsafe { libc::geteuid() }
        || meta.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,"Unsafe Luna socket"));
    }
    let socket = UnixDatagram::unbound()?;
    socket.connect(path)?;
    let sent = socket.send(request.wire())?;
    if sent != request.wire().len() {
        return Err(io::Error::new(io::ErrorKind::WriteZero,"Short desktop request"));
    }
    Ok(())
}

pub fn receive(socket: &UnixDatagram) -> io::Result<Option<Request>> {
    let mut message = [0_u8; 64];
    match socket.recv(&mut message) {
        Ok(count) => Ok(Request::decode(&message[..count])),
        Err(err) if err.kind() == io::ErrorKind::WouldBlock => Ok(None),
        Err(err) => Err(err),
    }
}

/// Resolve the configured Desktop location only if it is a real user-owned
/// directory. Never create folders in HOME or an arbitrary recipe path.
fn desktop_folder() -> io::Result<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from)
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound,"No HOME"))?;
    if !home.is_absolute() { return Err(io::ErrorKind::InvalidInput.into()); }
    let candidate = std::process::Command::new("xdg-user-dir").arg("DESKTOP")
        .output().ok().filter(|result| result.status.success())
        .and_then(|result| String::from_utf8(result.stdout).ok())
        .map(|path| PathBuf::from(path.trim()))
        .filter(|path| path.is_absolute() && path != &home)
        .unwrap_or_else(|| home.join("Desktop"));
    let info = fs::symlink_metadata(&candidate)?;
    if !info.is_dir() || info.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                                  "Desktop must be an owned non-symlink directory"));
    }
    Ok(candidate)
}

fn new_folder_in(dir: &Path) -> io::Result<PathBuf> {
    for attempt in 1..=100 {
        let label = if attempt == 1 { "New Folder".to_owned() }
                    else { format!("New Folder ({attempt})") };
        let candidate = dir.join(label);
        match fs::create_dir(&candidate) {
            Ok(()) => return Ok(candidate),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(io::ErrorKind::AlreadyExists,"No unused folder name"))
}

pub fn new_folder() -> io::Result<PathBuf> {
    new_folder_in(&desktop_folder()?)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn requests_are_allowlisted_and_exact() {
        for (command, request) in [
            ("arrange",Request::Arrange),
            ("new-folder",Request::NewFolder),
            ("refresh",Request::Refresh),
            ("properties",Request::Properties),
            ("show-desktop",Request::ShowDesktop),
            ("run",Request::Run),
            ("explorer",Request::Explorer),
        ] {
            assert_eq!(Request::parse(command), Some(request));
            assert_eq!(Request::decode(request.wire()), Some(request));
        }
        for invalid in [b"arrange;rm".as_slice(), b"refresh\0", b"new-folder/../",
                        b"explorer /etc", b"show-desktop\n", b"run;sh"] {
            assert_eq!(Request::decode(invalid),None);
        }
    }

    #[test]
    fn owner_private_socket_round_trip_and_cleanup() {
        use std::os::unix::fs::DirBuilderExt;
        use std::time::{SystemTime,UNIX_EPOCH};
        let n=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir=env::temp_dir().join(format!("luna-ipc-{}-{n}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        let path=dir.join("request.sock");
        let socket=UnixDatagram::bind(&path).unwrap();
        socket.set_nonblocking(true).unwrap();
        let sender=UnixDatagram::unbound().unwrap();
        sender.connect(&path).unwrap();
        sender.send(Request::Refresh.wire()).unwrap();
        assert_eq!(receive(&socket).unwrap(),Some(Request::Refresh));
        assert_eq!(receive(&socket).unwrap(),None);
        fs::remove_file(path).unwrap();
        fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn safe_new_folder_creates_real_unique_directories_without_overwriting() {
        use std::{os::unix::fs::DirBuilderExt,time::{SystemTime,UNIX_EPOCH}};
        let n=SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root=env::temp_dir().join(format!("luna-folders-{}-{n}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&root).unwrap();
        let first=new_folder_in(&root).unwrap();
        assert_eq!(first.file_name().unwrap(),"New Folder");
        let marker=first.join("keep.txt");
        fs::write(&marker,b"important").unwrap();
        let second=new_folder_in(&root).unwrap();
        assert_eq!(second.file_name().unwrap(),"New Folder (2)");
        assert_eq!(fs::read(&marker).unwrap(),b"important");
        assert!(Request::parse("new-folder;rm").is_none());
        fs::remove_file(marker).unwrap();
        fs::remove_dir(first).unwrap();
        fs::remove_dir(second).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
