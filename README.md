# vibe-buff 🔔

**English** | [Русский](README.ru.md)

**An overlay timer that reminds you to recast your in-game skill while you're vibe coding.**

You have a game running in one window where you need to stand still and press
one button every N seconds. Meanwhile you're writing code, reading docs, or
chatting with an AI. A couple of minutes later you've forgotten about the game,
and your buff is gone.

vibe-buff watches your skill key. When you press it, a countdown starts on a
small always-on-top panel. When time is almost up, the panel turns orange. When
time runs out, it flashes **«ОБНОВИ!»** ("Recast!") and plays a soft bell chime
until you press the key again.

## Example: Warframe, Survival with Khora

You're holding a Survival mission with Strangledome (Khora's dome, bound to `4`
by default) while vibe coding in another window:

1. Run `skill_timer.pyw`.
2. Right-click the panel → «Скилл [R]» → «Настроить…» (Configure).
3. Name the timer (e.g. "Dome"), click «Кнопка» (Key) and press `4`. Set the
   dome duration from your build (check it in the Arsenal) and a warning about
   5 seconds before the end.
4. Cast the dome and the timer starts on its own. When you hear the
   "ding-dong", go back to the game and recast it.

It works for any game with buffs, shields, auras, potions, or totems on a
timer.

## Features

- Semi-transparent, always-on-top panel you can drag with the mouse.
- Catches key presses globally, keyboard and side mouse buttons
  (Mouse4/Mouse5), even while the game or your editor has focus.
- Multiple timers, each with its own key.
- Lock mode (**Ctrl+Alt+L**): clicks pass through the panel.
- A soft bell chime instead of a harsh beep, with adjustable volume. You can
  use your own `.wav` (the `sound_file` field in the config).
- Settings and panel position are saved to `skill_timer_config.json`.

> The interface is currently in Russian.

## Running

You need Windows and Python 3.8+ (tkinter ships with the standard installer).
There are no third-party dependencies.

```bash
pythonw skill_timer.pyw
```

Or just double-click `skill_timer.pyw`.

## Controls

| Action | What it does |
|---|---|
| Bound key | (re)starts the timer |
| Left-click + drag | moves the panel |
| Right-click | menu: add / configure / remove a timer, general settings, exit |
| × next to a timer | stops the timer and the chime |
| ✕ in the corner | closes the overlay |
| Ctrl+Alt+L | lock / unlock (click-through) |
| Ctrl+Alt+X | stops all timers (works in lock mode too) |

## Notes

- Run the game in **borderless windowed** mode. Windows doesn't draw other
  windows over exclusive fullscreen.
- The program only *reads* whether a key is pressed (`GetAsyncKeyState`). It
  never presses anything for you, doesn't inject into the game, and doesn't read
  its memory. It's a reminder, not a macro.
- In the config, `key` is a Windows virtual-key code, not the character:
  the `4` key is `52`, and `4` itself is the middle mouse button. The easiest
  way to bind a key is through the settings dialog.
