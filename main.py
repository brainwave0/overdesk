#!/usr/bin/python3
from xcffib import connect, xproto
from xcffib.xproto import MotionNotifyEvent, ConfigWindow, GetPropertyType
from ewmh import EWMH
from sys import argv, exit
import pynput
from pynput.mouse import Button
from time import sleep
import cProfile


def get_mouse_position(mouse):
    def on_move(x, y):
        return False

    with pynput.mouse.Listener(on_move=on_move) as listener:
        listener.join()
    return mouse.position


def map_to_virtual(mouse_position, original_position, screen_size,
                   virtual_size):
    ratio = (virtual_size[0] / screen_size[0],
             virtual_size[1] / screen_size[1])
    size_difference = (screen_size[0] - virtual_size[0],
                       screen_size[1] - virtual_size[1])
    mouse_delta = (mouse_position[0] - screen_size[0] / 2,
                   mouse_position[1] - screen_size[1] / 2)
    return (-round(original_position[0] + mouse_delta[0] * ratio[0] +
                   size_difference[0]),
            -round(original_position[1] + mouse_delta[1] * ratio[1] +
                   size_difference[1]))


def add_new_window(connection, window, root_id, window_data, mouse_position,
                   screen_size, virtual_size):
    extents = get_frame_extents(connection, window.id, window_data)
    geometry = get_window_geometry(connection, window.id, root_id, extents)
    window_data[window.id] = {}
    window_data[window.id]["original_position"] = map_to_virtual(
        mouse_position, geometry[0], screen_size, virtual_size)
    window_data[window.id]["types"] = ewmh.getWmWindowType(window, str=True)
    window_data[window.id]["extents"] = extents
    window_data[window.id]["position"] = geometry[0]
    window_data[window.id]["size"] = geometry[1]


def move_windows(connection, mouse_position, windows, screen_size,
                 virtual_size, root_id, window_data):
    global dragged_window
    for window in windows:
        if window.id not in window_data:
            add_new_window(connection, window, root_id, window_data,
                           mouse_position, screen_size, virtual_size)
        window_types = window_data[window.id]["types"]
        if "_NET_WM_WINDOW_TYPE_NORMAL" in window_types:
            extents = window_data[window.id]["extents"]
            position = window_data[window.id]["position"]
            size = window_data[window.id]["size"]
            dragging_window = check_dragging_window(mouse_position, position,
                                                    size, extents, window.id)
            if dragging_window:
                dragged_window = window.id
            else:
                if window.id == dragged_window:
                    geometry = get_window_geometry(connection, window.id,
                                                   root_id, extents)
                    window_data[
                        window.id]["original_position"] = map_to_virtual(
                            mouse_position, geometry[0], screen_size,
                            virtual_size)
                    window_data[window.id]["position"] = geometry[0]
                    window_data[window.id]["size"] = geometry[1]
                    dragged_window = None
                new_coords = map_to_virtual(
                    mouse_position,
                    window_data[window.id]["original_position"], screen_size,
                    virtual_size)
                set_window_geometry(connection, window.id, new_coords[0],
                                    new_coords[1])
                window_data[window.id]["position"] = new_coords


def get_window_geometry(connection, window_id, root_id, extents):
    a = connection.core.TranslateCoordinates(window_id, root_id, 0, 0).reply()
    b = connection.core.GetGeometry(window_id).reply()
    position = (a.dst_x - b.x, a.dst_y - b.y)
    size = (b.width, b.height)
    return (position, size)


def set_window_geometry(connection,
                        window_id,
                        x=None,
                        y=None,
                        width=None,
                        height=None):
    properties = 0
    values = []
    if x is not None:
        properties = properties | ConfigWindow.X
        values.append(x)
    if y is not None:
        properties = properties | ConfigWindow.Y
        values.append(y)
    if width is not None:
        properties = properties | ConfigWindow.Width
        values.append(width)
    if height is not None:
        properties = properties | ConfigWindow.Height
        values.append(height)
    connection.core.ConfigureWindow(window_id, properties, values)


def get_frame_extents(connection, window_id, window_data):
    _NET_FRAME_EXTENTS = connection.core.InternAtom(
        True, len("_NET_FRAME_EXTENTS"), "_NET_FRAME_EXTENTS").reply().atom
    extent_bytes = connection.core.GetProperty(False, window_id,
                                               _NET_FRAME_EXTENTS,
                                               GetPropertyType.Any, 0,
                                               2**32 - 1).reply().value
    results = []
    for i in range(4):
        results.append(
            int.from_bytes(b''.join(extent_bytes[i * 4:i * 4 + 1]), "little"))
    extents = results
    return results


def handle_click(x, y, button, pressed):
    global lmb_pressed
    if button == Button.left:
        lmb_pressed = pressed


def cursor_on_titlebar(mouse_position, position, size, extents):
    result = position[0] <= mouse_position[0] <= position[0] + size[
        0] and position[1] <= mouse_position[1] <= position[1] + extents[2]
    return result


def check_dragging_window(mouse_position, position, size, extents, window_id):
    global dragged_window
    global lmb_pressed
    result = cursor_on_titlebar(
        mouse_position, position, size,
        extents) and lmb_pressed or window_id == dragged_window and lmb_pressed
    return result


ewmh = EWMH()
connection = connect()
root_id = connection.setup.roots[0].root
mouse = pynput.mouse.Controller()
screen_geometry = connection.core.GetGeometry(
    ewmh.display.screen().root.id).reply()
screen_size = (screen_geometry.width, screen_geometry.height)
screen_center = (round(screen_size[0] / 2), round(screen_size[1] / 2))
mouse.position = screen_center
lmb_pressed = None
mouse_listener = pynput.mouse.Listener(on_click=handle_click)
mouse_listener.start()
virtual_size = (int(argv[-2]), int(argv[-1]))
original_positions = {}
windows = None
while windows is None:
    try:
        windows = ewmh.getClientList()
        break
    except TypeError:
        continue
mouse_position = mouse.position
last_position = mouse_position
window_data = {}
for window in windows:
    add_new_window(connection, window, root_id, window_data, mouse_position,
                   screen_size, virtual_size)
dragged_window = None
extents = None
while True:
    sleep(1 / 60)
    mouse_position = connection.core.QueryPointer(root_id).reply()
    mouse_position = (mouse_position.root_x, mouse_position.root_y)
    if mouse_position == last_position:
        continue
    windows = ewmh.getClientList()
    move_windows(connection, mouse_position, windows, screen_size,
                 virtual_size, root_id, window_data)
    last_position = mouse_position