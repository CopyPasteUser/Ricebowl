//! Single-owner process lifecycle for RicePlate's external application launcher.
//! A rice may invoke only the fixed fuzzel action; no recipe command reaches here.
//! This avoids duplicate popups and reaps completed children without a resident poller.

use std::{io, process::{Child, Command, Stdio}};

#[derive(Default)]
pub(crate) struct ExternalLauncher {
    child: Option<Child>,
}

impl ExternalLauncher {
    /// Returns false when the existing launcher is still alive. A new request
    /// cannot create a second keyboard-grabbing surface before it closes.
    pub(crate) fn activate(&mut self) -> io::Result<bool> {
        self.start("fuzzel", &[])
    }

    fn start(&mut self, program: &str, args: &[&str]) -> io::Result<bool> {
        self.reap()?;
        if self.child.is_some() {
            return Ok(false);
        }
        self.child = Some(Command::new(program).args(args)
            .stdin(Stdio::null()).spawn()?);
        Ok(true)
    }

    /// Called on ordinary Wayland event-loop wakes, not by a background
    /// thread or timer. Children are checked non-blockingly.
    pub(crate) fn reap(&mut self) -> io::Result<()> {
        if let Some(child) = self.child.as_mut() {
            if child.try_wait()?.is_some() {
                self.child = None;
            }
        }
        Ok(())
    }
}

impl Drop for ExternalLauncher {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.take() {
            // A rice switch tears down the old native panel. It must not
            // strand an active external keyboard-grabbing launcher.
            if matches!(child.try_wait(), Ok(None)) {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn double_activation_does_not_create_parallel_launcher_processes() {
        let mut launcher = ExternalLauncher::default();
        assert!(launcher.start("sleep", &["5"]).unwrap());
        let original = launcher.child.as_ref().unwrap().id();
        assert!(!launcher.start("sleep", &["5"]).unwrap());
        assert_eq!(launcher.child.as_ref().unwrap().id(), original);
        launcher.child.as_mut().unwrap().kill().unwrap();
        launcher.child.as_mut().unwrap().wait().unwrap();
        // The completed child must be reaped before the next activation.
        assert!(launcher.start("sleep", &["5"]).unwrap());
        assert_ne!(launcher.child.as_ref().unwrap().id(), original);
    }

    #[test]
    fn failed_spawn_never_creates_false_busy_state() {
        let mut launcher = ExternalLauncher::default();
        assert!(launcher.start("/nonexistent/ricebowl-ci-fuzzel", &[]).is_err());
        assert!(launcher.child.is_none());
        assert!(launcher.start("true", &[]).unwrap());
        launcher.child.as_mut().unwrap().wait().unwrap();
        assert!(launcher.reap().is_ok());
        assert!(launcher.child.is_none());
    }
}
