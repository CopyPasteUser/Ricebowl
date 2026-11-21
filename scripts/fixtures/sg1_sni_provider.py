#!/usr/bin/python3
"""Disposable, unprivileged StatusNotifierItem + DBusMenu integration provider.

Runs ONLY on the caller's session bus. No system bus, daemon installation,
privileged method, user file, or application configuration is touched.
Use dbus-run-session and a private receipt/ready directory from the smoke.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

SERVICE = "org.ricebowl.SNIFixture"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
CONTROL = "org.ricebowl.SNIFixtureControl"
XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/>
      <arg type="as" direction="in"/><arg type="u" direction="out"/>
      <arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" direction="in"/><arg type="b" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
  </interface>
  <interface name="org.ricebowl.SNIFixtureControl">
    <method name="SetMode"><arg type="s" direction="in"/></method>
    <method name="Quit"/>
  </interface>
</node>
"""
MODES = {"normal", "disabled", "removed", "empty", "denied", "slow"}


def node(item_id, properties, children=()):
    # D-BusMenu's children are variants of (ia{sv}av), NOT bare structs.
    return (item_id, properties, [
        GLib.Variant("(ia{sv}av)", child) for child in children
    ])


def props(label, *, enabled=True, submenu=False):
    result = {"label": GLib.Variant("s", label),
              "enabled": GLib.Variant("b", enabled),
              "visible": GLib.Variant("b", True)}
    if submenu:
        result["children-display"] = GLib.Variant("s", "submenu")
    return result


class Fixture:
    def __init__(self, args):
        self.args = args
        self.loop = GLib.MainLoop()
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.revision = 1
        self.mode = args.mode
        self.registered = False
        self.finished = False
        self.ready = Path(args.ready)
        self.receipts = Path(args.receipts)
        self.ready.parent.mkdir(parents=True, exist_ok=True)
        self.receipts.parent.mkdir(parents=True, exist_ok=True)
        self.interface_info = {item.name: item for item in
            Gio.DBusNodeInfo.new_for_xml(XML).interfaces}
        for path, name in (("/StatusNotifierItem", ITEM), ("/Menu", MENU),
                           ("/Control", CONTROL)):
            self.connection.register_object(
                path, self.interface_info[name], self.method, self.get_property, None)
        response = self.connection.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "RequestName",
            GLib.Variant("(su)", (SERVICE, 4)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 2000, None)
        if response.unpack()[0] != 1:
            raise RuntimeError("SNI fixture name already has an owner")
        self.receipt("owner", bus=self.connection.get_unique_name())

    def receipt(self, event, **fields):
        line = json.dumps({"generation": self.args.generation, "event": event,
                           **fields}, sort_keys=True) + "\n"
        fd = os.open(self.receipts, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def get_property(self, connection, sender, object_path, interface, name):
        if interface == ITEM:
            values = {
                "Category": GLib.Variant("s", "ApplicationStatus"),
                "Id": GLib.Variant("s", "ricebowl-sg1-test"),
                "Title": GLib.Variant("s", "SNI fixture " + self.args.generation),
                "Status": GLib.Variant("s", "Active"),
                "IconName": GLib.Variant("s", "dialog-information"),
                "IconPixmap": GLib.Variant("a(iiay)", []),
                "ItemIsMenu": GLib.Variant("b", True),
                "Menu": GLib.Variant("o", "/Menu"),
            }
        elif interface == MENU:
            values = {
                "Version": GLib.Variant("u", 3),
                "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"),
                "IconThemePath": GLib.Variant("as", []),
            }
        else:
            return None
        return values.get(name)

    def layout(self, parent_id):
        action = node(10, props("Provider action"))
        denied = node(11, props("Denied action", enabled=self.mode != "disabled"))
        child = node(21, props("Nested action"))
        submenu = node(20, props("Submenu", submenu=True), [child])
        children = [submenu, action, denied]
        if self.mode == "removed":
            children = [submenu, denied]
        elif self.mode == "empty":
            children = []
        if parent_id == 20:
            return submenu
        return node(0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def method(self, connection, sender, path, interface, name, params, invocation):
        if interface == CONTROL:
            if name == "SetMode":
                mode = params.unpack()[0]
                if mode not in MODES:
                    invocation.return_dbus_error("org.ricebowl.InvalidMode", "Unknown fixture mode")
                    return
                self.mode = mode
                self.revision += 1
                self.receipt("mode", mode=mode)
                self.connection.emit_signal(None, "/Menu", MENU, "LayoutUpdated",
                                            GLib.Variant("(ui)", (self.revision, 0)))
            elif name == "Quit":
                GLib.idle_add(self.loop.quit)
            invocation.return_value(GLib.Variant("()", ()))
            return

        if interface == ITEM:
            self.receipt("item", method=name, coords=list(params.unpack()))
            invocation.return_value(GLib.Variant("()", ()))
            return

        if name == "GetLayout":
            parent_id = params.unpack()[0]
            self.receipt("layout", parent=parent_id, mode=self.mode)
            layout = self.layout(parent_id)
            result = GLib.Variant("(u(ia{sv}av))", (self.revision, layout))
            if self.mode == "slow":
                GLib.timeout_add(500, self.reply_once, invocation, result)
            else:
                invocation.return_value(result)
            return
        if name == "AboutToShow":
            self.receipt("about-to-show", id=params.unpack()[0])
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return
        if name == "Event":
            item_id, action, _data, _timestamp = params.unpack()
            self.receipt("menu-event", id=item_id, action=action, mode=self.mode)
            if item_id not in (0, 10, 11, 20, 21):
                invocation.return_dbus_error("org.ricebowl.UnknownMenuId",
                                             "Unknown action ID")
            elif self.mode == "denied" and action == "clicked":
                invocation.return_dbus_error("org.ricebowl.AccessDenied",
                                             "Injected provider failure")
            elif (self.mode == "removed" and item_id == 10) or self.mode == "empty":
                invocation.return_dbus_error("org.ricebowl.RevokedMenuId",
                                             "Action has been removed")
            elif self.mode == "disabled" and item_id == 11 and action == "clicked":
                invocation.return_dbus_error("org.ricebowl.DisabledMenuId",
                                             "Action is disabled")
            else:
                invocation.return_value(GLib.Variant("()", ()))
            return
        invocation.return_dbus_error("org.ricebowl.UnknownMethod", name)

    @staticmethod
    def reply_once(invocation, value):
        invocation.return_value(value)
        return GLib.SOURCE_REMOVE

    def register(self):
        if self.registered:
            return GLib.SOURCE_REMOVE
        try:
            self.connection.call_sync(
                "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (SERVICE,)),
                GLib.VariantType.new("()"), Gio.DBusCallFlags.NONE, 500, None)
        except GLib.Error:
            return GLib.SOURCE_CONTINUE
        self.registered = True
        self.receipt("registered")
        self.ready.write_text(self.connection.get_unique_name() + "\n", encoding="utf-8")
        self.ready.chmod(0o600)
        return GLib.SOURCE_REMOVE

    def run(self):
        if not self.args.no_register:
            GLib.timeout_add(150, self.register)
        signal.signal(signal.SIGTERM, lambda *_: self.loop.quit())
        self.loop.run()
        self.receipt("exit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", required=True)
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--mode", choices=sorted(MODES), default="normal")
    parser.add_argument("--no-register", action="store_true",
                        help="Only for direct protocol tests without a watcher")
    args = parser.parse_args()
    Fixture(args).run()


if __name__ == "__main__":
    main()
