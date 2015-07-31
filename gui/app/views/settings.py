#!/usr/bin/env python
# encoding: utf-8

# Stdlib:
import re
from operator import itemgetter
from functools import partial

# Internal:
from app.util import View, SuggestedButton, DestructiveButton
from app.filesizerange import FileSizeRange

# External:
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gio
from gi.repository import GObject


def boolean_widget(settings, key_name, summary, description):
    switch = Gtk.Switch()
    settings.bind(key_name, switch, 'active', 0)
    switch.set_active(settings.get_boolean(key_name))
    return switch


def _format_range_value(spin, draw_size, draw_percent):
    adj = spin.get_adjustment()
    value = adj.get_value()

    if draw_size:
        spin.set_text('{}'.format(value))
        return True
    elif draw_percent:
        spin.set_text('{}'.format(value * 100))
        return True
    return False


def numeric_widget(
    settings, key_name, summary, description,
    floating_point=False, draw_percent=False, draw_size=True
):
    schema = settings.get_property('settings-schema')
    key = schema.get_key(key_name)
    range_type, range_variant = key.get_range()

    step = 0.1 if floating_point else 1
    range_wdgt = Gtk.SpinButton.new_with_range(0, 10 ** 10, step)

    if range_type == 'range':
        min_val, max_val = range_variant
        range_wdgt.set_range(min_val, max_val)

    settings.bind(key_name, range_wdgt, 'value', 0)

    if floating_point:
        value = settings.get_double(key_name)
    else:
        value = settings.get_int(key_name)

    range_wdgt.set_value(value)
    # TODO: For weird reasons this is not working.
    range_wdgt.connect('output', _format_range_value, draw_size, draw_percent)
    return range_wdgt


class InteractiveLevelBar(Gtk.ProgressBar):
    def __init__(self):
        Gtk.ProgressBar.__init__(self)
        self.set_can_focus(True)
        self.grab_focus()

        # Enable the receival of the appropiate signals:
        self.add_events(self.get_events() |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.SCROLL_MASK
        )

        self.set_size_request(100, 15)
        self.connect(
            'button-press-event',
            InteractiveLevelBar._on_button_press
        )

    def set_value(self, value):
        # Gtk.LevelBar.set_value(self, value)
        self.set_fraction(value)

    def _on_button_press(self, event):
        if event.type == Gdk.EventType.BUTTON_RELEASE:
            alloc = self.get_allocation()
            percent = event.x / alloc.width
            self.set_value(percent)
            return True
        return False


def range_widget(settings, key_name, summary, description):
    min_val, max_val = settings.get_value(key_name)
    widget = FileSizeRange(min_val, max_val)

    def _changed(*_):
        min_val, max_val = settings.get_value(key_name)
        widget.props.min_value = min_val
        widget.props.max_value = max_val

    settings.connect('changed::' + key_name, _changed)

    return widget


class _ChoiceRow(Gtk.ListBoxRow):
    def __init__(self, value, is_default):
        Gtk.ListBoxRow.__init__(self)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        label = Gtk.Label(value.capitalize())
        label.props.xalign = 0

        self.value, self.is_default = value, is_default
        self.set_can_focus(False)

        self.set_margin_left(3)
        self.set_margin_right(3)

        self.symbol = Gtk.Image.new_from_gicon(
            Gio.ThemedIcon(name='emblem-ok-symbolic'),
            Gtk.IconSize.BUTTON
        )
        self.symbol.set_no_show_all(True)

        box.pack_start(label, True, True, 0)
        box.pack_start(self.symbol, False, False, 0)
        self.add(box)

    def set_show_checkmark(self, state):
        self.symbol.set_visible(state or self.is_default)

        if self.is_default and not state:
            icon_name, dim_down = 'non-starred-symbolic', True
        elif self.is_default and state:
            icon_name, dim_down = 'starred-symbolic', False
        elif not self.is_default and state:
            icon_name, dim_down = 'emblem-ok-symbolic', False
        else:
            icon_name, dim_down = None, False

        if icon_name is not None:
            self.symbol.set_from_gicon(
                Gio.ThemedIcon(name=icon_name), Gtk.IconSize.BUTTON
            )

        ctx = self.symbol.get_style_context()
        if dim_down:
            ctx.add_class(Gtk.STYLE_CLASS_DIM_LABEL)
            self.symbol.set_opacity(0.5)
        else:
            ctx.remove_class(Gtk.STYLE_CLASS_DIM_LABEL)
            self.symbol.set_opacity(1.0)


class _CurrentChoiceLabel(Gtk.Label):
    def __init__(self, text):
        Gtk.Label.__init__(self)

        self.set_use_markup(True)
        self.pretty_text = text

    @GObject.Property(type=str, default='')
    def choice(self):
        self._choice

    @choice.setter
    def set_choice(self, new_value):
        self._choice = new_value
        self.set_markup(
            '<u>{v}</u>'.format(
                v=self._choice.capitalize()
            )
        )

        self.notify('choice')



class MultipleChoiceButton(Gtk.Button):
    def __init__(self, values, default, selected, summary):
        Gtk.Button.__init__(self)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(False)

        self.value_label = _CurrentChoiceLabel(default)
        self.add(self.value_label)

        popover = Gtk.Popover.new(self)
        popover.set_modal(True)

        listbox = Gtk.ListBox()
        listbox.set_border_width(10)
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.set_activate_on_single_click(True)

        listbox.connect('row-activated', self.on_update_value)
        listbox_header = Gtk.Label(
            '<small><b>{txt}?</b></small>'.format(txt=summary)
        )
        listbox_header.get_style_context().add_class(
            Gtk.STYLE_CLASS_DIM_LABEL
        )
        listbox_header.set_use_markup(True)
        listbox_header.set_size_request(90, -1)

        for widget in Gtk.Separator(), listbox_header:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            row.add(widget)
            listbox.prepend(row)

        frame = Gtk.Frame()
        frame.add(listbox)
        frame.set_border_width(5)
        popover.add(frame)

        for choice in values:
            row = _ChoiceRow(choice, default == choice)
            listbox.add(row)

            if choice == selected:
                listbox.select_row(row)
                row.set_show_checkmark(True)

        self.connect('clicked', lambda *_: popover.show_all())

    def on_update_value(self, listbox, row):
        for other_row in listbox:
            # Might be a different type:
            if isinstance(other_row, _ChoiceRow):
                other_row.set_show_checkmark(row is other_row)

        settings.set_string(key_name, row.value)
        popover.hide()


def choice_widget(settings, key_name, summary, description):
    schema = settings.props.settings_schema
    key = schema.get_key(key_name)

    selected = settings.get_string(key_name)
    default = key.get_default_value().get_string()

    range_type, range_variant = key.get_range()
    if range_type != 'enum':
        print('uh oh')

    choices = list(range_variant)
    button = MultipleChoiceButton(choices, default, selected, summary)
    button.connect('clicked', lambda *_: popover.show_all())
    settings.bind(key_name, button.value_label, 'choice', 0)

    return button


VARIANT_TO_WIDGET = {
    'b': boolean_widget,
    'i': partial(numeric_widget, floating_point=False),
    'd': partial(numeric_widget, floating_point=True),
    's': choice_widget,
    '(ii)': range_widget,
    '(tt)': range_widget
}


class SettingsView(View):
    def __init__(self, app):
        View.__init__(
            self, app, sub_title='Configure how duplicates are searched'
        )

        self._grid = Gtk.Grid()
        self._grid.set_margin_left(30)
        self._grid.set_margin_right(40)
        self._grid.set_margin_top(5)
        self._grid.set_margin_bottom(15)
        self._grid.set_hexpand(True)
        self._grid.set_vexpand(True)
        self._grid.set_halign(Gtk.Align.FILL)
        self._grid.set_valign(Gtk.Align.FILL)
        self.add(self._grid)

        self.save_settings = False
        self.sections = {}

        self.appy_btn = SuggestedButton()
        self.deny_btn = DestructiveButton('Reset to defaults')

        self.appy_btn.connect('clicked', self.on_apply_settings)
        self.deny_btn.connect('clicked', self.on_reset_to_defaults)

        self.fill_from_settings()

    def append_section(self, heading):
        box = Gtk.ListBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)
        box.set_size_request(350, -1)
        box.set_hexpand(True)

        frame = Gtk.Frame()
        frame.set_halign(Gtk.Align.FILL)
        frame.add(box)

        label = Gtk.Label()
        label.set_margin_top(30)
        label.set_markup(
            '<b>{}:</b>'.format(GLib.markup_escape_text(heading, -1))
        )
        label.set_halign(Gtk.Align.START)
        label.set_margin_bottom(2)

        self.sections[heading.lower()] = box
        self._grid.attach(label, 0, len(self._grid), 1, 1)
        self._grid.attach(frame, 0, len(self._grid), 1, 1)

    def append_entry(self, section, key_name, val_widget, summary, desc=None):
        desc_label = Gtk.Label(desc or '')
        summ_label = Gtk.Label(summary or '')

        desc_label.get_style_context().add_class(
            Gtk.STYLE_CLASS_DIM_LABEL
        )

        for label in desc_label, summ_label:
            label.set_use_markup(True)
            label.set_halign(Gtk.Align.FILL)
            label.set_hexpand(True)
            label.set_halign(Gtk.Align.START)

        val_widget.set_halign(Gtk.Align.END)

        sub_grid = Gtk.Grid()
        sub_grid.attach(summ_label, 0, 0, 1, 1)
        sub_grid.attach(desc_label, 0, 1, 1, 1)
        sub_grid.attach(val_widget, 1, 0, 1, 2)
        sub_grid.set_border_width(3)

        listbox = self.sections[section.lower()]

        if len(listbox) is not 0:
            sep_row = Gtk.ListBoxRow()
            sep_row.set_activatable(False)
            sep_row.add(Gtk.Separator())
            listbox.insert(sep_row, -1)

        row = Gtk.ListBoxRow()
        row.add(sub_grid)
        row.set_can_focus(False)
        listbox.insert(row, -1)

    def reset_to_defaults(self):
        for key_name in self.app.settings.list_keys():
            self.app.settings.reset(key_name)

    def fill_from_settings(self):
        gst = self.app.settings
        schema = gst.get_property('settings-schema')

        entry_rows = []

        for key_name in gst.list_keys():
            key = schema.get_key(key_name)
            variant_key = gst.get_value(key_name)

            # Try to find a way to render this option:
            constructor = VARIANT_TO_WIDGET.get(variant_key.get_type_string())
            if constructor is None:
                continue

            # Get the key summary and description:
            summary = '{}'.format(key.get_summary())

            # This is an extension of this code:
            if summary.startswith('[hidden]'):
                continue

            order, order_match = 0, re.match('\[(\d+)]\s(.*)', summary)
            if order_match is not None:
                order, summary = int(order_match.group(1)), order_match.group(2)

            description = key.get_description()
            if description:
                description = '<small>{desc}</small>'.format(
                    desc=key.get_description()
                )

            # Get a fitting, readily prepared configure widget
            val_widget = constructor(gst, key_name, summary, description)

            # Try to find the section name by the keyname.
            # This is an extension made by this code and not part of GSettings.
            section = ''
            if '-' in key_name:
                section, _ = key_name.split('-', maxsplit=1)

            entry_rows.append(
                (order, section, key_name, val_widget, summary, description)
            )

        for section in sorted(set(map(itemgetter(1), entry_rows))):
            self.append_section(section.capitalize())

        for entry in sorted(entry_rows, key=itemgetter(0, 2)):
            self.append_entry(*entry[1:])

    def on_view_enter(self):
        self.save_settings = False
        self.app.settings.delay()

        # Give the buttons a specific context meaning:
        self.on_key_changed(self.app.settings, None)
        self.app.settings.connect('changed', self.on_key_changed)

        self.app_window.add_header_widget(self.appy_btn)
        self.app_window.add_header_widget(self.deny_btn, Gtk.Align.START)

    def on_view_leave(self):
        self.app_window.remove_header_widget(self.appy_btn)
        self.app_window.remove_header_widget(self.deny_btn)
        if self.save_settings:
            self.app.settings.apply()
        else:
            self.app.settings.revert()

    def on_apply_settings(self, *_):
        self.save_settings = True
        self.app_window.views.switch_to_previous()

    def on_reset_to_defaults(self, *_):
        self.app.settings.revert()

        GLib.timeout_add(
            100, lambda: self.reset_to_defaults() or self.app.settings.delay()
        )

        self.save_settings = False

    def on_key_changed(self, settings, _):
        is_sensitive = settings.get_has_unapplied()
        self.appy_btn.set_sensitive(is_sensitive)
        self.deny_btn.set_sensitive(is_sensitive)