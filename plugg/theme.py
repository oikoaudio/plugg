"""Oiko visual roles, adapted for a desktop GTK manager."""
from pathlib import Path

PALETTES = {
    'dark': dict(page='#171817', panel='#202220', text='#EEEEE8', muted='#A7AAA1', border='#3A3D38', field='#171817', hover='#30332F', accent='#FFAD5C', selection='#5BAACF', error='#EB5B46', accent_text='#171817', ok='#8CC084',
                 m0='#4E6B5E', m1='#5E5A80', m2='#80594A', m3='#4A6680', m4='#776D45', m5='#6E4E62', mono_text='#EEEEE8'),
    'light': dict(page='#E8E8E5', panel='#F6F6F2', text='#161715', muted='#4A4D46', border='#AEB3AA', field='#D7D9D3', hover='#C5C9C0', accent='#A63D05', selection='#123797', error='#B02A20', accent_text='#F6F6F2', ok='#2E7D32',
                  m0='#B9D3C6', m1='#CAC6E6', m2='#E6C8BC', m3='#BCD0E6', m4='#DDD5B2', m5='#DEC3D3', mono_text='#161715'),
}


def css(mode='dark'):
    roles = PALETTES[mode]
    definitions = '\n'.join(f'@define-color oiko_{key} {value};' for key,value in roles.items())
    return (definitions + '''
window { background: @oiko_page; color: @oiko_text; font-family: Ubuntu, sans-serif; }
headerbar { background: @oiko_panel; color: @oiko_text; border-bottom: none; box-shadow: none; }
headerbar button { padding: 4px 8px; }
.app-tabs button { min-width: 0; padding: 7px 10px; }
.app-tabs button:checked { background: @oiko_selection; color: @oiko_panel; border-color: @oiko_selection; }
.hero { font-size: 1.43em; font-weight: 600; }
.subtitle, .muted { color: @oiko_muted; }
.section-title { font-size: 1.29em; font-weight: 500; }
.plugin-name { font-size: 1.29em; font-weight: 500; }
.status { font-size: 0.79em; color: @oiko_muted; }
.drop-area { background: @oiko_panel; border: 1px solid alpha(@oiko_accent, 0.35); border-radius: 10px; padding: 24px; min-height: 100px; }
.card { background: @oiko_panel; border: 1px solid @oiko_border; border-radius: 8px; padding: 12px; }
.component-card { padding: 10px; }
.component-purpose { color: @oiko_text; opacity: 1; }
.card-title { font-size: 1.07em; font-weight: 500; color: @oiko_text; opacity: 1; }
button.count { padding: 1px 8px; min-height: 18px; font-size: 0.86em; color: @oiko_muted; }
.plugin-row { padding: 4px 12px; border-radius: 6px; }
.plugin-row:hover { background: @oiko_hover; }
button, dropdown > button { background: @oiko_panel; color: @oiko_text; border: 1px solid @oiko_border; border-radius: 6px; padding: 7px 12px; min-height: 24px; box-shadow: none; }
.compact-icon > button { padding: 4px; min-height: 20px; min-width: 20px; }
button.compact { padding: 4px 10px; min-height: 20px; font-size: 0.93em; }
button.destructive { background: @oiko_error; color: @oiko_panel; border-color: @oiko_error; }
button.destructive:disabled { opacity: 0.4; }
button.dim { opacity: 0.6; }
button.recipe-link { padding: 2px 0; min-height: 20px; border: none; background: transparent; color: @oiko_selection; }
button.recipe-link:hover { text-decoration: underline; }
.compact-icon image { -gtk-icon-size: 16px; }
button:hover { background: @oiko_hover; }
button:focus-visible, entry:focus { outline: 2px solid @oiko_selection; outline-offset: 2px; }
button.suggested-action { background: @oiko_accent; color: @oiko_accent_text; border-color: @oiko_accent; }
button:disabled { opacity: 0.45; }
entry, searchentry { background: @oiko_field; color: @oiko_text; border: 1px solid @oiko_border; border-radius: 6px; padding: 8px; min-height: 24px; }
popover > contents { background: @oiko_panel; color: @oiko_text; border: 1px solid @oiko_border; }
expander > title { padding: 12px 4px; font-size: 1.29em; color: @oiko_text; }
/* A section header reads as one bar across the window. The folding one is the
   expander's own title, so the whole bar — arrow included — is the hit area. */
.section-header, expander.section > title { background: @oiko_panel; border: 1px solid @oiko_border; border-radius: 8px; padding: 10px 14px; }
expander.section > title:hover { background: @oiko_hover; }
selection { background: @oiko_selection; color: @oiko_panel; }
.error { color: @oiko_error; }
/* Running, but its window may be hidden: visibly live rather than greyed out. */
button.running { border-color: @oiko_accent; color: @oiko_accent; }
button.running:hover { background: alpha(@oiko_accent, 0.12); }
.running-note { font-size: 0.79em; color: @oiko_accent; }
/* What a recipe declares, ranked. The colour is the ranking; the sentence
   beside it is what tells someone whether to care. */
.chip { font-size: 0.79em; padding: 2px 8px; border-radius: 999px; border: 1px solid @oiko_border; color: @oiko_muted; }
.chip-danger { color: @oiko_error; border-color: @oiko_error; }
.chip-caution { color: @oiko_accent; border-color: @oiko_accent; }
.flag-danger { color: @oiko_error; }
.flag-caution { color: @oiko_accent; }
.pinned { font-family: monospace; font-size: 0.79em; color: @oiko_muted; }
/* The library list. Figures and identifiers are monospace with even digits,
   so sizes line up down the column the way they do in a terminal; everything
   a person reads as words stays in the interface font. */
.library searchentry { padding: 6px 10px; }
.lib-section { margin-top: 18px; margin-bottom: 2px; }
.lib-section-title { font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
                     font-size: 0.79em; letter-spacing: 1px; text-transform: uppercase; color: @oiko_muted; }
.lib-section separator { background: @oiko_border; min-height: 1px; }
.lib-list, list.lib-list { background: @oiko_panel; border: 1px solid alpha(@oiko_border, 0.7); border-radius: 10px; padding: 0; }
list.lib-list > row.lib-item { padding: 12px 16px 10px 16px; border-top: 1px solid alpha(@oiko_border, 0.5);
                               background: transparent; }
list.lib-list > row.lib-item:first-child { border-top: none; }
list.lib-list > row.lib-item:hover { background: alpha(@oiko_text, 0.025); }
/* Where the keyboard is: a solid ring inside the row, so the hairlines stay put.
   The view adds .keyboard while it is driven by keys (see LibraryView.show_focus). */
list.lib-list > row.lib-item:focus-visible,
.library.keyboard list.lib-list > row.lib-item:focus { box-shadow: inset 0 0 0 2px @oiko_selection;
                                                        background: alpha(@oiko_selection, 0.08); }
list.lib-list > row.lib-urgent { border-left: 3px solid @oiko_accent; padding-left: 13px; }
/* Cleanup is housekeeping: a folded line under the vendors, not a banner. */
expander.lib-cleanup { margin-top: 18px; }
expander.lib-cleanup > title { padding: 4px 0; }
popover.lib-menu > contents { padding: 4px; min-width: 260px; }
button.lib-menu-item { background: transparent; border: none; padding: 6px 10px; min-height: 22px; font-weight: normal; }
button.lib-menu-item:hover { background: @oiko_hover; }
button.lib-menu-danger { color: @oiko_error; }
popover.lib-menu separator { margin: 4px 0; background: alpha(@oiko_border, 0.6); }
.lib-name { font-size: 1.07em; font-weight: 500; }
.lib-meta, .lib-figure, .lib-plugin, .lib-chip { font-family: "JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace;
                                                   font-feature-settings: "tnum"; }
.lib-meta { font-size: 0.79em; color: @oiko_muted; }
.lib-figure { font-size: 0.93em; color: @oiko_text; }
.lib-dim { color: @oiko_muted; }
.lib-note { font-size: 0.86em; color: @oiko_muted; }
.lib-chip { font-size: 0.71em; padding: 1px 7px; border-radius: 4px; border: 1px solid @oiko_border; color: @oiko_muted; }
.lib-chip-caution { color: @oiko_accent; border-color: alpha(@oiko_accent, 0.6); }
.lib-plugin { font-size: 0.79em; padding: 2px 8px; border-radius: 4px; background: alpha(@oiko_text, 0.05);
              color: @oiko_text; }
.lib-plugin-waiting { background: transparent; border: 1px dashed alpha(@oiko_text, 0.25); color: @oiko_muted; }
.lib-plugin-hit { background: alpha(@oiko_selection, 0.25); }
progressbar.lib-bar trough { min-height: 3px; background: alpha(@oiko_text, 0.07); border: none; border-radius: 2px; }
progressbar.lib-bar progress { min-height: 3px; background: alpha(@oiko_text, 0.35); border: none; border-radius: 2px; }
.lib-details { padding-top: 8px; }
button.lib-toggle { padding: 2px; min-height: 22px; min-width: 22px; background: transparent; border: none; }
button.lib-toggle:hover { background: @oiko_hover; }
menubutton.lib-toggle > button { padding: 2px; min-height: 22px; min-width: 22px; background: transparent; border: none;
                                 color: @oiko_muted; }
menubutton.lib-toggle > button:hover { background: @oiko_hover; color: @oiko_text; }
button.lib-quiet { background: transparent; border-color: transparent; color: @oiko_muted; }
button.lib-quiet:hover { color: @oiko_text; background: @oiko_hover; }
button.lib-danger { background: transparent; color: @oiko_error; border-color: alpha(@oiko_error, 0.5); }
button.lib-danger:hover { background: alpha(@oiko_error, 0.12); }
.drop-area.drop-compact { padding: 10px 14px; min-height: 0; border-color: alpha(@oiko_accent, 0.25); }
.window-title { font-weight: 600; }
.lib-preview { font-size: 0.86em; color: @oiko_selection; padding: 8px 12px; border-radius: 6px;
               background: alpha(@oiko_selection, 0.10); }
.lib-dot { min-width: 8px; min-height: 8px; border-radius: 4px; background: alpha(@oiko_text, 0.25); }
.lib-dot-ok { background: @oiko_ok; }
.lib-dot-waiting { background: @oiko_accent; }
.lib-dot-running { background: @oiko_selection; }
.lib-mono { border-radius: 8px; font-weight: 600; font-size: 0.86em; color: @oiko_mono_text; }
.lib-mono-0 { background: @oiko_m0; } .lib-mono-1 { background: @oiko_m1; } .lib-mono-2 { background: @oiko_m2; }
.lib-mono-3 { background: @oiko_m3; } .lib-mono-4 { background: @oiko_m4; } .lib-mono-5 { background: @oiko_m5; }
progressbar.lib-bar-warm progress { background: alpha(@oiko_accent, 0.6); }
.lib-footer { margin-top: 18px; padding-top: 10px; border-top: 1px solid alpha(@oiko_border, 0.6); }
/* Text size follows the desktop's own setting: every size above is relative
   to the window font, which GTK takes from the system (Large Text included). */
@media (prefers-contrast: more) {
  .subtitle, .muted, .status, .lib-meta, .lib-dim, .lib-note, .lib-section-title { color: @oiko_text; }
  .lib-list, list.lib-list, .lib-section separator { border-color: @oiko_text; }
  list.lib-list > row.lib-item { border-top-color: alpha(@oiko_text, 0.6); }
  list.lib-list > row.lib-item:focus-visible,
  .library.keyboard list.lib-list > row.lib-item:focus { box-shadow: inset 0 0 0 3px @oiko_selection; }
  button:focus-visible { outline-width: 3px; }
  .lib-plugin-waiting { border-style: solid; }
}
''').encode()


def install_font():
    # Private application font registration; does not install fonts for the desktop.
    import ctypes
    import ctypes.util
    library = ctypes.util.find_library('fontconfig')
    if not library:
        return False
    font = Path(__file__).parent / 'assets/Ubuntu-Regular.ttf'
    if not font.exists():
        return False
    fc = ctypes.CDLL(library)
    fc.FcConfigGetCurrent.restype = ctypes.c_void_p
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    fc.FcConfigAppFontAddFile.restype = ctypes.c_int
    return bool(fc.FcConfigAppFontAddFile(fc.FcConfigGetCurrent(), str(font).encode()))
