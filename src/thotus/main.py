#!/usr/bin/python2
import sys
import traceback
from time import time

from thotus.ui import gui
from thotus import control
from thotus import settings
from thotus import commands as cmds
from thotus.scanner import get_controllers

from prompt_toolkit import prompt
from prompt_toolkit.contrib.completers import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.token import Token
from prompt_toolkit.styles import style_from_dict

history = InMemoryHistory()

def s2h(t):
    if t > 80:
        return "%d min %ds"%divmod(t, 60)
    else:
        return "%.1fs"%t

def get_bottom_toolbar_tokens(cli):
    if not timers:
        txt = ' Welcome!'
    else:
        txt = "Last command executed in %s"%(s2h(timers['end_execution']-timers['execution']))
    return [(Token.Toolbar, txt)]

style = style_from_dict({
    Token.Toolbar: '#ffffff bg:#333333',
})

leave_now = False
DEBUG = True

def exit():
    global leave_now
    leave_now = True
    return 3

def help():
    print("Commands:")
    for c in sorted(commands):
        if c.startswith('cam_'):
            d = 'get or set camera %s'%c[4:].strip()
        else:
            d = commands[c].__doc__
        if d:
            d = d.strip().title()
        else:
            d = ""
        print(" %-20s  %s"%(c, d.title()))
    return 3

def toggle_advanced_mode():
    """ toggle advanced command set """
    if 'debug_settings' in commands:
        for cmd in adv_commands:
            del commands[cmd]
        print("Using simple commands")
    else:
        commands.update(adv_commands)
        print("Using advanced commands")

commands = dict(
    # calibrate
    calibrate_full = cmds.fullcalibrate,
    calibrate      = cmds.stdcalibrate,
    advanced       = toggle_advanced_mode,

    # all in one scan
    scan           = cmds.scan,

    # misc
    view           = cmds.view,
    rotate         = control.rotate,
    lasers         = control.switch_lasers,
    exit           = exit,
    quit           = exit,
    help           = help,
    keep_laser     = cmds.set_single_laser,
    roi            = cmds.set_roi,
    )

adv_commands = dict(
    debug_settings = settings.compare,

    # compute calibration data
    recalibrate      = cmds.calibrate,
    recalibrate_pure = cmds.calibrate_pure,
    recalibrate_cam  = control.toggle_cam_calibration,

    # acquire pictures
    capture          = cmds.capture,
    capture_color    = cmds.capture_color,
    capture_lasers   = cmds.capture_lasers,

    pattern          = cmds.capture_pattern,
    pattern_colors   = cmds.capture_pattern_colors,
    pattern_lasers   = cmds.capture_pattern_lasers,

    # build 3D mesh
    make          = cmds.recognize,
    make_pure     = cmds.recognize_pure,

    use_horus_cfg    = cmds.set_horus_cfg,
    use_thot_cfg     = cmds.set_thot_cfg,
)

try:
    commands.update(get_controllers())
except IndexError:
    print("Unable to find camera, is it plugged ?")

timers = dict()

def wanna_leave():
    global leave_now
    print("Aborted !")
    try:
        text = prompt(u'Exit (Y/n) ? ', completer=WordCompleter( ('yes', 'no') , ignore_case=True
        ))
    except (KeyboardInterrupt, EOFError):
        leave_now = True
    else:
        if not text or text.lower()[0] != 'n':
            leave_now = True

leave_after = False
if len(sys.argv) > 1:
    text = ' '.join(sys.argv[1:])
    sys.argv[:] = [sys.argv[0]]
    leave_after = True
    toggle_advanced_mode()

if not leave_after:
    try:
        cmds.view()
    except Exception as e:
        pass

while not leave_now:
    if not leave_after:
        try:
            text = prompt(u'Scan Bot> ',
                    history=history,
                    get_bottom_toolbar_tokens=get_bottom_toolbar_tokens,
                    style=style,
                    completer = WordCompleter(commands, ignore_case=True, match_middle=False,
                        )
                    )
        except EOFError:
            break
        except KeyboardInterrupt:
            wanna_leave()

    if leave_now:
        break

    timers['execution'] = time()
    if text.strip():
        if ' ' in text:
            params = text.split()
            text = params[0]
            params = params[1:]
        else:
            params = ()
        try:
            if commands[text](*params) != 3:
                print("")
        except KeyboardInterrupt:
            gui.clear()
            wanna_leave()
        except KeyError:
            print("Command not found: %s"%text)
        except Exception as e:
            gui.clear()
            print("")
            if DEBUG:
                traceback.print_exc()
            else:
                print("Error occured")
    timers['end_execution'] = time()
    if leave_after:
        leave_now = True

cmds.stop()
