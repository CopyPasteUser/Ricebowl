//! Focus-scoped, event-driven wl_data_device clipboard for native Luna editors.
//! No wl-copy helper, persistent clipboard daemon, shell, or local fake paste.
//! All untrusted remote bytes remain private until an EOF-terminated,
//! bounded UTF-8 transfer is validated atomically by luna_dialog::State.
use std::{
    io::{Read, Write}, os::fd::AsFd, os::unix::net::UnixStream,
    time::{Duration, Instant},
};

use wayland_client::{
    protocol::{
        wl_data_device::{self, WlDataDevice},
        wl_data_device_manager::{self, WlDataDeviceManager},
        wl_data_offer::{self, WlDataOffer},
        wl_data_source::{self, WlDataSource},
        wl_seat, wl_surface,
    },
    Connection, Dispatch, QueueHandle,
};

use crate::{luna_dialog, RicePlate};

const UTF8: &str = "text/plain;charset=utf-8";
const PLAIN: &str = "text/plain";
const MAX_BYTES: usize = luna_dialog::MAX_INPUT * 4;
const TRANSFER_TIMEOUT: Duration = Duration::from_secs(3);

struct Pending {
    reader: UnixStream,
    bytes: Vec<u8>,
    started: Instant,
    target: wl_surface::WlSurface,
    prior_text: String,
    prior_cursor: usize,
    prior_anchor: Option<usize>,
}

pub(crate) struct Completed {
    pub target: wl_surface::WlSurface,
    pub text: String,
    pub prior_text: String,
    pub prior_cursor: usize,
    pub prior_anchor: Option<usize>,
}

pub(crate) struct Clipboard {
    manager: Option<WlDataDeviceManager>,
    device: Option<WlDataDevice>,
    source: Option<WlDataSource>,
    owned_text: Option<String>,
    offers: Vec<(WlDataOffer, Vec<String>)>,
    selected: Option<WlDataOffer>,
    pending: Option<Pending>,
}

impl Clipboard {
    pub fn new(manager: Option<WlDataDeviceManager>) -> Self {
        Self {
            manager, device: None, source: None, owned_text: None,
            offers: Vec::new(), selected: None, pending: None,
        }
    }

    pub fn attach(&mut self, seat: &wl_seat::WlSeat, qh: &QueueHandle<RicePlate>) {
        if self.device.is_none() {
            if let Some(manager) = self.manager.as_ref() {
                self.device = Some(manager.get_data_device(seat, qh, ()));
            }
        }
    }

    pub fn detach(&mut self) {
        self.cancel_paste();
        if let Some(source) = self.source.take() { source.destroy(); }
        self.owned_text = None;
        for (offer, _) in self.offers.drain(..) { offer.destroy(); }
        self.selected = None;
        if let Some(device) = self.device.take() { device.release(); }
    }

    /// An active compositor keyboard serial authorizes this selection. Never
    /// mutate the editor before this request is created successfully.
    pub fn copy(&mut self, text: &str, serial: u32,
                qh: &QueueHandle<RicePlate>) -> bool {
        if text.is_empty() || text.len() > MAX_BYTES { return false; }
        let (Some(manager), Some(device)) = (self.manager.as_ref(), self.device.as_ref())
            else { return false; };
        let source = manager.create_data_source(qh, ());
        source.offer(UTF8.to_owned());
        source.offer(PLAIN.to_owned());
        device.set_selection(Some(&source), serial);
        if let Some(old) = self.source.replace(source) { old.destroy(); }
        self.owned_text = Some(text.to_owned());
        true
    }

    pub fn cancel_paste(&mut self) { self.pending = None; }

    pub fn paste_pending(&self) -> bool { self.pending.is_some() }

    /// Request a genuine wl_data_offer.receive, not a cached local clipboard
    /// approximation. The transfer is asynchronous and never blocks Wayland
    /// event dispatch while another application owns the selection.
    pub fn begin_paste(&mut self, target: &wl_surface::WlSurface,
                       state: &luna_dialog::State) -> bool {
        let Some(offer) = self.selected.as_ref() else { return false; };
        let Some((_, types)) = self.offers.iter().find(|(proxy, _)| proxy == offer)
            else { return false; };
        let mime = if types.iter().any(|m| m == UTF8) { UTF8 }
            else if types.iter().any(|m| m == PLAIN) { PLAIN }
            else { return false; };
        let Ok((reader, writer)) = UnixStream::pair() else { return false; };
        if reader.set_nonblocking(true).is_err() { return false; }
        self.cancel_paste();
        offer.receive(mime.to_owned(), writer.as_fd());
        drop(writer);
        self.pending = Some(Pending {
            reader, bytes: Vec::with_capacity(MAX_BYTES),
            started: Instant::now(), target: target.clone(),
            prior_text: state.input.clone(), prior_cursor: state.cursor,
            prior_anchor: state.selection_anchor,
        });
        true
    }

    /// Called only while one paste is outstanding; a short deadline wakes
    /// the existing event loop instead of starting a resident polling task.
    pub fn poll(&mut self, now: Instant) -> Option<Completed> {
        let mut pending = self.pending.take()?;
        if now.duration_since(pending.started) >= TRANSFER_TIMEOUT { return None; }
        let mut chunk = [0_u8; 1024];
        loop {
            match pending.reader.read(&mut chunk) {
                Ok(0) => {
                    let text = String::from_utf8(pending.bytes).ok()?;
                    if text.is_empty() || text.len() > MAX_BYTES { return None; }
                    return Some(Completed {
                        target: pending.target, text,
                        prior_text: pending.prior_text,
                        prior_cursor: pending.prior_cursor,
                        prior_anchor: pending.prior_anchor,
                    });
                }
                Ok(n) => {
                    if n > MAX_BYTES.saturating_sub(pending.bytes.len()) {
                        return None; // overflow is never a truncated paste
                    }
                    pending.bytes.extend_from_slice(&chunk[..n]);
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    self.pending = Some(pending);
                    return None;
                }
                Err(_) => return None,
            }
        }
    }

    fn offer(&mut self, offer: WlDataOffer) {
        // Drag offers are not clipboard selections; do not accumulate them.
        if self.offers.len() >= 16 {
            let (old, _) = self.offers.remove(0);
            if self.selected.as_ref() != Some(&old) { old.destroy(); }
        }
        self.offers.push((offer, Vec::new()));
    }

    fn select(&mut self, selected: Option<WlDataOffer>) {
        self.selected = selected.clone();
        let old = std::mem::take(&mut self.offers);
        for (offer, types) in old {
            if selected.as_ref() == Some(&offer) {
                self.offers.push((offer, types));
            } else {
                offer.destroy();
            }
        }
    }
}

impl Dispatch<WlDataDeviceManager, ()> for RicePlate {
    fn event(_: &mut Self, _: &WlDataDeviceManager,
             _: wl_data_device_manager::Event, _: &(),
             _: &Connection, _: &QueueHandle<Self>) {}
}

impl Dispatch<WlDataDevice, ()> for RicePlate {
    fn event(state: &mut Self, proxy: &WlDataDevice,
             event: wl_data_device::Event, _: &(),
             _: &Connection, _: &QueueHandle<Self>) {
        if state.clipboard.device.as_ref() != Some(proxy) { return; }
        match event {
            wl_data_device::Event::DataOffer { id } => state.clipboard.offer(id),
            wl_data_device::Event::Selection { id } => state.clipboard.select(id),
            _ => {} // ignore drag/drop; never interpret dropped data as text
        }
    }
}

impl Dispatch<WlDataOffer, ()> for RicePlate {
    fn event(state: &mut Self, offer: &WlDataOffer,
             event: wl_data_offer::Event, _: &(),
             _: &Connection, _: &QueueHandle<Self>) {
        if let wl_data_offer::Event::Offer { mime_type } = event {
            if let Some((_, types)) = state.clipboard.offers.iter_mut()
                .find(|(proxy, _)| proxy == offer) {
                if types.len() < 16 && mime_type.len() < 128 {
                    types.push(mime_type);
                }
            }
        }
    }
}

impl Dispatch<WlDataSource, ()> for RicePlate {
    fn event(state: &mut Self, source: &WlDataSource,
             event: wl_data_source::Event, _: &(),
             _: &Connection, _: &QueueHandle<Self>) {
        if state.clipboard.source.as_ref() != Some(source) { return; }
        match event {
            wl_data_source::Event::Send { mime_type, fd } => {
                let mut file = std::fs::File::from(fd);
                if mime_type == UTF8 || mime_type == PLAIN {
                    if let Some(text) = state.clipboard.owned_text.as_ref() {
                        let _ = file.write_all(text.as_bytes());
                    }
                }
            }
            wl_data_source::Event::Cancelled => {
                if let Some(source) = state.clipboard.source.take() {
                    source.destroy();
                }
                state.clipboard.owned_text = None;
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn utf8_transfer_limit_covers_maximum_editor_scalars() {
        assert_eq!(MAX_BYTES, 768);
        assert_eq!("🧪".repeat(luna_dialog::MAX_INPUT).len(), MAX_BYTES);
        assert!("🧪".repeat(luna_dialog::MAX_INPUT + 1).len() > MAX_BYTES);
    }
    #[test]
    fn clipboard_without_seat_never_claims_ownership() {
        let mut clipboard = Clipboard::new(None);
        assert!(!clipboard.copy("private", 1, unreachable_queue_for_test()));
    }
    fn unreachable_queue_for_test() -> &'static QueueHandle<RicePlate> {
        // Intentionally never called: verify capability guard before any
        // protocol request requires a live compositor or fake clipboard.
        panic!("no Wayland queue should be needed to reject clipboard")
    }
}
