//! Opt-in Luna desktop root-menu bridge. The compositor already owns the
//! background right-click: do not create a transparent fullscreen layer.
//! Only fixed, allowlisted commands cross the local owner-private datagram socket.
use std::{env,ffi::CString,fs::{self,OpenOptions},io,os::{fd::AsRawFd,unix::{fs::{FileTypeExt,MetadataExt,OpenOptionsExt,PermissionsExt},net::UnixDatagram}},
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

fn socket_path_for(runtime: &Path, nested: bool, session: Option<&Path>)
    -> io::Result<PathBuf>
{
    if !runtime.is_absolute() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput,
                                  "Non-absolute runtime directory"));
    }
    let uid = unsafe { libc::geteuid() };
    let stat = fs::symlink_metadata(runtime)?;
    if !stat.is_dir() || stat.uid() != uid || stat.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                                  "Unsafe runtime directory"));
    }
    if !nested {
        return Ok(runtime.join("riceplate-luna-desktop.sock"));
    }
    // Nested previews run under the *same* user account as a real session.
    // Never reuse the full-login socket or send nested actions to that session.
    // The disposable private labwc config is unique to the running compositor
    // and inherited by both the panel and labwc's root-menu commands.
    let directory = session.ok_or_else(|| io::Error::new(
        io::ErrorKind::NotFound, "Missing isolated nested session directory"))?;
    if !directory.is_absolute() || directory.parent() != Some(runtime)
        || !directory.file_name().is_some_and(|name|
            name.to_str().is_some_and(|name| name.starts_with("ricebowl-labwc-")))
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput,
                                  "Invalid nested session directory"));
    }
    let info = fs::symlink_metadata(directory)?;
    if !info.is_dir() || info.uid() != uid
        || info.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                                  "Unsafe nested session directory"));
    }
    let marker = fs::symlink_metadata(directory.join(".ricebowl-managed"))?;
    if !marker.is_file() || marker.uid() != uid
        || marker.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                                  "Unmanaged nested session directory"));
    }
    Ok(directory.join("riceplate-luna-desktop.sock"))
}

fn socket_path() -> io::Result<PathBuf> {
    let dir = env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from)
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound,"No runtime directory"))?;
    let nested = env::var("RICEBOWL_DE_NESTED").as_deref() == Ok("1");
    let session = env::var_os("RICEBOWL_DE_SESSION_CONFIG").map(PathBuf::from);
    socket_path_for(&dir, nested, session.as_deref())
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
    // Pin the checked Desktop directory before modifying it. mkdirat never
    // follows a newly substituted symlink or writes into a replacement path
    // between the directory validation and folder creation.
    let parent = OpenOptions::new().read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(dir)?;
    let original = parent.metadata()?;
    if !original.is_dir() || original.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied,
                                  "Desktop directory is not owned by the user"));
    }
    for attempt in 1..=100 {
        let label = if attempt == 1 { "New Folder".to_owned() }
                    else { format!("New Folder ({attempt})") };
        let name = CString::new(label.as_bytes()).expect("fixed folder label");
        let result = unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o700) };
        if result == 0 {
            // A renamed directory is still safely modified through parent,
            // but its former pathname must not be passed to a file manager.
            let current = fs::symlink_metadata(dir)?;
            if !current.is_dir() || current.dev() != original.dev()
                || current.ino() != original.ino() {
                return Err(io::Error::new(io::ErrorKind::NotFound,
                                          "Desktop directory moved during creation"));
            }
            return Ok(dir.join(label));
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::AlreadyExists { return Err(error); }
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
    fn new_folder_rejects_symlinked_parent_and_does_not_follow_name_collision() {
        use std::{os::unix::fs::{DirBuilderExt, symlink},
                  time::{SystemTime,UNIX_EPOCH}};
        let n = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let root = env::temp_dir().join(format!("luna-folder-safety-{}-{n}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&root).unwrap();
        let target = root.join("target");
        fs::create_dir(&target).unwrap();
        fs::write(target.join("keep"), b"important").unwrap();
        symlink(&target, root.join("New Folder")).unwrap();
        let created = new_folder_in(&root).unwrap();
        assert_eq!(created.file_name().unwrap(),"New Folder (2)");
        assert!(created.is_dir());
        assert_eq!(fs::symlink_metadata(&created).unwrap().mode() & 0o077, 0);
        assert_eq!(fs::read(target.join("keep")).unwrap(), b"important");
        let alias = root.with_extension("alias");
        symlink(&root, &alias).unwrap();
        assert!(new_folder_in(&alias).is_err(), "symlinked Desktop root rejected");
        assert_eq!(fs::read(target.join("keep")).unwrap(), b"important");
        fs::remove_file(alias).unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn nested_root_menu_socket_is_unique_and_never_targets_real_session() {
        use std::{os::unix::fs::{DirBuilderExt, symlink},
                  time::{SystemTime, UNIX_EPOCH}};
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let runtime = env::temp_dir().join(format!("luna-nested-{}-{now}",std::process::id()));
        fs::DirBuilder::new().mode(0o700).create(&runtime).unwrap();
        let nested = runtime.join("ricebowl-labwc-accepted");
        fs::DirBuilder::new().mode(0o700).create(&nested).unwrap();
        let marker = nested.join(".ricebowl-managed");
        fs::write(&marker, b"").unwrap();
        fs::set_permissions(&marker, fs::Permissions::from_mode(0o600)).unwrap();

        let real = socket_path_for(&runtime, false, None).unwrap();
        let private = socket_path_for(&runtime, true, Some(&nested)).unwrap();
        assert_ne!(real, private);
        assert_eq!(real.parent(), Some(runtime.as_path()));
        assert_eq!(private.parent(), Some(nested.as_path()));
        assert!(socket_path_for(&runtime, true, None).is_err());
        assert!(socket_path_for(&runtime, true, Some(&runtime)).is_err());
        let other = runtime.join("unmanaged");
        fs::DirBuilder::new().mode(0o700).create(&other).unwrap();
        assert!(socket_path_for(&runtime, true, Some(&other)).is_err());
        let alias = runtime.join("ricebowl-labwc-alias");
        symlink(&nested, &alias).unwrap();
        assert!(socket_path_for(&runtime, true, Some(&alias)).is_err());
        fs::remove_file(&alias).unwrap();
        fs::remove_dir(&other).unwrap();
        fs::set_permissions(&nested, fs::Permissions::from_mode(0o755)).unwrap();
        assert!(socket_path_for(&runtime, true, Some(&nested)).is_err());
        fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
        fs::remove_file(&marker).unwrap();
        assert!(socket_path_for(&runtime, true, Some(&nested)).is_err());
        fs::remove_dir(&nested).unwrap();
        fs::remove_dir(&runtime).unwrap();
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
