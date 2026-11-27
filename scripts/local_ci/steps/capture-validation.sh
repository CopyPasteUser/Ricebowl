#!/bin/bash
# local-ci step: capture-validation
# Mirrors: riceplate-native.yml / native-layer-shell / Validate and record real multi-resolution captures
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
python3 - <<'PY'
import hashlib
import json
import subprocess
from pathlib import Path
import struct
from PIL import Image
from scripts.compare_wayland_captures import compare

directory = Path('dist/riceplate-native-preview')
private_recipe = directory / 'desktop-v5-recipe.json'
private_recipe.write_bytes(Path('tests/fixtures/riceplate-desktop-v5.json').read_bytes())
private_recipe.chmod(0o600)
manifest = {
    'manifest_version': 1,
    'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'environment': {'compositor': 'labwc', 'backend': 'headless',
                    'renderer': 'pixman', 'native_surface': 'riceplate'},
    'recipe_sha256': hashlib.sha256(private_recipe.read_bytes()).hexdigest(),
    'captures': [],
}
expected = {
    'desktop-v5-1024x768': (1024, 768, 1),
    'desktop-v5-1366x768': (1366, 768, 1),
    'desktop-v5-1920x1080': (1920, 1080, 1),
    'desktop-v5-scale-125': (1366, 768, 1.25),
    'overflow-v5': (1024, 768, 1),
    'creator-v1': (1024, 768, 1),
    'isolated-v5': (1024, 768, 1),
    'layout-v8': (1366, 768, 1),
    'components-v9': (1366, 768, 1),
    'desktop-actions-v9': (1366, 768, 1),
    'appearance-v10': (1366, 768, 1),
    'xp-luna-columns': (1366, 768, 1),
    'xp-luna-default-icons': (1366, 768, 1),
    'xp-luna-columns-menu': (1366, 768, 1),
    'xp-luna-font-menu': (1366, 768, 1),
    'xp-luna-columns-calendar': (1366, 768, 1),
    'xp-luna-font-calendar': (1366, 768, 1),
    'xp-luna-columns-osd': (1366, 768, 1),
    'xp-luna-font-osd': (1366, 768, 1),
    'xp-luna-columns-notifications': (1366, 768, 1),
    'xp-luna-columns-notifications-scroll': (1366, 768, 1),
    'xp-luna-font-notifications': (1366, 768, 1),
    'xp-luna-columns-notification-detail': (1366, 768, 1),
    'xp-luna-font-notification-detail': (1366, 768, 1),
    'xp-luna-columns-1024x768': (1024, 768, 1),
    'xp-luna-columns-1366x768': (1366, 768, 1),
    'xp-luna-columns-1920x1080': (1920, 1080, 1),
    'xp-luna-columns-scale-125': (1366, 768, 1.25),
    'xp-luna-columns-menu-1024x768': (1024, 768, 1),
    'xp-luna-columns-menu-1366x768': (1366, 768, 1),
    'xp-luna-columns-menu-1920x1080': (1920, 1080, 1),
    'xp-luna-columns-menu-scale-125': (1366, 768, 1.25),
}
captures = {}
for label in ('shell-v4', 'desktop-v5', 'menu-v5', 'calendar-v5', *expected):
    screenshot = Path(f'dist/riceplate-native-preview/{label}.png')
    data = screenshot.read_bytes()
    assert data[:8] == bytes.fromhex('89504e470d0a1a0a'), f'{label}: not a PNG capture'
    width, height = struct.unpack('>II', data[16:24])
    assert width >= 640 and height >= 480, (label, width, height)
    assert len(data) >= 512, f'{label}: missing screenshot pixels'
    if label in expected:
        target_width, target_height, scale = expected[label]
        assert (width, height) == (target_width, target_height), (label, width, height)
        record = {
            'file': screenshot.name,
            'width': width, 'height': height, 'scale': scale,
            'sha256': hashlib.sha256(data).hexdigest(),
        }
        if label in ('overflow-v5', 'creator-v1'):
            # A requested x=4090 icon is intentionally invisible
            # without native output-aware reflow. With 1024x768
            # logical bounds it must be clamped to (920, 672).
            with Image.open(screenshot) as image:
                rgb = image.convert('RGB').getpixel((950, 690))
            assert all(abs(actual - expected_color) <= 2 for actual, expected_color in
                       zip(rgb, (65, 121, 170))), f'icon was not reflowed: {rgb}'
            record['reflow_pixel'] = {'x': 950, 'y': 690, 'rgb': rgb}
            if label == 'creator-v1':
                receipt = json.loads((directory / 'creator-v1.json').read_text())
                assert receipt['ok'] and receipt['creator_contract_version'] == 1
                assert receipt['capture']['source'] == 'current-wayland-compositor'
                assert receipt['capture']['sha256'] == record['sha256']
                assert receipt['capture']['width'] == width
                assert receipt['capture']['height'] == height
        elif label == 'isolated-v5':
            receipt = json.loads((directory / 'isolated-v5.json').read_text())
            assert receipt['ok'] and receipt['creator_contract_version'] == 1
            assert receipt['render']['source'] == 'isolated-headless-labwc-native-riceplate'
            assert receipt['render']['recipe']['id'] == 'mockup-desktop'
            assert receipt['render']['output']['sha256'] == record['sha256']
            assert receipt['render']['geometry'] == {
                'width': 1024, 'height': 768, 'scale': 1.0}
            with Image.open(screenshot) as image:
                rgb = image.convert('RGB').getpixel((64, 112))
            assert all(abs(actual - expected_color) <= 2 for actual, expected_color in
                       zip(rgb, (65, 121, 170))), f'native icon missing: {rgb}'
            record['native_icon_pixel'] = {'x': 64, 'y': 112, 'rgb': rgb}
        else:
            # Self-comparison is solely a geometry preflight, not
            # an assessment of visual fidelity or interaction.
            report = compare(screenshot, screenshot, recipe_token=str(private_recipe.resolve()))
            assert not report['layout_issues'], (label, report['layout_issues'])
            record['regions'] = [
                {key: region[key] for key in ('id', 'expected_rect', 'visible_fraction')}
                for region in report['regions']]
        manifest['captures'].append(record)
    print(f'Captured real native labwc {label}: {width}x{height}, {len(data)} bytes')
    captures[label] = data
assert captures['shell-v4'] != captures['desktop-v5'], 'Icons missing from v5 framebuffer'
assert captures['menu-v5'] != captures['desktop-v5'], 'Native menu did not render in Wayland frame'
assert captures['xp-luna-columns-menu'] != captures['xp-luna-columns'], \
    'XP Luna two-column Start menu was not rendered in real Wayland frame'
with Image.open(directory / 'xp-luna-columns.png') as closed_image, \
     Image.open(directory / 'xp-luna-columns-menu.png') as opened_image:
    region = (0, 338, 400, 718)
    closed = closed_image.convert('RGB').crop(region)
    opened = opened_image.convert('RGB').crop(region)
    menu_pixels = sum(a != b for a, b in zip(closed.getdata(), opened.getdata()))
    assert menu_pixels > 10000, \
        f'Native Luna menu missing after output configure: {menu_pixels}'
with Image.open(directory / 'xp-luna-default-icons.png') as original_image, \
     Image.open(directory / 'xp-luna-columns.png') as luna_image:
    # Compare the actual Programs shortcut (second desktop column).
    # The first shortcut now opens My Computer and intentionally has
    # the same native artwork in both variants. Programs alone changes
    # from default to original Luna artwork; keep the pixel threshold.
    region = (164, 92, 212, 140)
    original = original_image.convert('RGB').crop(region)
    luna = luna_image.convert('RGB').crop(region)
    icon_changed = sum(a != b for a, b in zip(original.getdata(), luna.getdata()))
assert icon_changed > 600, \
    f'Original Luna pictogram not visible on real compositor: {icon_changed}'
with Image.open(directory / 'xp-luna-columns-menu.png') as base_image, \
     Image.open(directory / 'xp-luna-font-menu.png') as font_image:
    base = base_image.convert('RGB').crop((0, 338, 400, 718))
    custom = font_image.convert('RGB').crop((0, 338, 400, 718))
    changed = sum(left != right for left, right in zip(base.getdata(), custom.getdata()))
    if changed <= 500:
        # A configure/resize race can remove the popup while the
        # desktop font still changes. Diagnose which region is gone
        # without weakening the real-menu glyph requirement.
        for region_name, region in (
            ('header', (0, 320, 500, 400)),
            ('body', (0, 400, 500, 700)),
            ('entire-left', (0, 250, 520, 728)),
        ):
            original_region = base_image.convert('RGB').crop(region)
            font_region = font_image.convert('RGB').crop(region)
            delta = sum(a != b for a, b in zip(original_region.getdata(),
                                                font_region.getdata()))
            print(f'Luna font pixel QA {region_name}: {delta}', flush=True)
assert changed > 500, f'Private TrueType did not change native menu glyph pixels: {changed}'
with Image.open(directory / 'xp-luna-columns-calendar.png') as bitmap_image, \
     Image.open(directory / 'xp-luna-font-calendar.png') as typeface_image:
    baseline = bitmap_image.convert('RGB').crop((1022, 376, 1358, 728))
    imported = typeface_image.convert('RGB').crop((1022, 376, 1358, 728))
    calendar_changed = sum(left != right for left, right in
                           zip(baseline.getdata(), imported.getdata()))
assert calendar_changed > 200, \
    f'Private TrueType did not change native calendar glyph pixels: {calendar_changed}'
with Image.open(directory / 'xp-luna-columns-osd.png') as bitmap_image, \
     Image.open(directory / 'xp-luna-font-osd.png') as typeface_image:
    # A flat OSD background must be visible in BOTH actual Wayland
    # frames; an absent popup must never pass on wallpaper noise.
    for frame in (bitmap_image, typeface_image):
        backdrop = frame.convert('RGB').getpixel((1110, 25))
        assert all(abs(actual - expected) <= 2 for actual, expected in
                   zip(backdrop, (36, 94, 211))), \
            f'Native Luna volume OSD was not visible: {backdrop}'
    # Earlier smoke scenarios can leave the output at 125% scale:
    # the 248px logical OSD then occupies ~310 physical pixels and
    # begins around x=1035, not 1102. Include both valid placements
    # so the left-side "Volume" label is never cropped away.
    osd_region = (1010, 10, 1360, 120)
    baseline = bitmap_image.convert('RGB').crop(osd_region)
    imported = typeface_image.convert('RGB').crop(osd_region)
    osd_changed = sum(left != right for left, right in
                      zip(baseline.getdata(), imported.getdata()))
# Full scaled OSD changed 880 RGB pixels in the first real capture;
# the initial 125-pixel measurement had clipped its left-side text.
assert osd_changed > 300, \
    f'Private TrueType did not change native volume OSD pixels: {osd_changed}'
for suffix in ('notifications', 'notification-detail'):
    with Image.open(directory / 'xp-luna-columns.png') as closed_image, \
         Image.open(directory / f'xp-luna-columns-{suffix}.png') as bitmap_image, \
         Image.open(directory / f'xp-luna-font-{suffix}.png') as font_image:
        # Compare the real compositor popup, not the changing panel
        # clock or the unrelated wallpaper elsewhere on the output.
        region = (0, 350, 330, 720)
        closed = closed_image.convert('RGB').crop(region)
        bitmap = bitmap_image.convert('RGB').crop(region)
        imported = font_image.convert('RGB').crop(region)
        popup_pixels = sum(a != b for a, b in zip(closed.getdata(), bitmap.getdata()))
        font_pixels = sum(a != b for a, b in zip(bitmap.getdata(), imported.getdata()))
    assert popup_pixels > 2500, \
        f'Native RicePop {suffix} not visible in compositor: {popup_pixels}'
    assert font_pixels > 250, \
        f'Private font did not change RicePop {suffix}: {font_pixels}'
# Use Creator's existing visual-QA engine on genuine paired frames;
# the output is a reviewable heatmap and per-region diagnosis, not
# a claim that the screenshots certify focus or accessibility.
luna_recipe = directory / 'xp-luna-visual-recipe.json'
luna_recipe.write_bytes(Path('examples/wayland/xp-luna-columns.json').read_bytes())
luna_recipe.chmod(0o600)
visual_reviews = []
for suffix, width, height in (
    ('1024x768', 1024, 768), ('1366x768', 1366, 768),
    ('1920x1080', 1920, 1080), ('scale-125', 1366, 768),
):
    # Every screenshot is from the SAME live native process after
    # wlr-randr reconfigures the compositor, not four isolated
    # recipe mocks. Keep both the separate wallpaper and taskbar.
    with Image.open(directory / f'xp-luna-columns-{suffix}.png') as desktop, \
         Image.open(directory / f'xp-luna-columns-menu-{suffix}.png') as menu:
        canvas = desktop.convert('RGB')
        opened = menu.convert('RGB')
        wallpaper = canvas.getpixel((width // 2, height // 3))
        assert sum(wallpaper) > 90, \
            f'Luna wallpaper missing after live {suffix} reconfigure: {wallpaper}'
        panel = canvas.getpixel((width // 2, height - 14))
        assert panel[2] > panel[1] + 25 and panel[2] > panel[0] + 25, \
            f'Luna blue taskbar missing after live {suffix} reconfigure: {panel}'
        region = (0, height - 450, min(width, 640), height - 50)
        closed_area = canvas.crop(region)
        opened_area = opened.crop(region)
        menu_changed = sum(a != b for a, b in zip(
            closed_area.getdata(), opened_area.getdata()))
        assert menu_changed > 10000, \
            f'Native Luna Start menu missing after live {suffix} reconfigure: {menu_changed}'
    before = directory / f'xp-luna-columns-{suffix}.png'
    after = directory / f'xp-luna-columns-menu-{suffix}.png'
    heatmap = (directory / f'luna-menu-diff-{suffix}.png').resolve()
    report = compare(before, after, recipe_token=str(luna_recipe.resolve()),
                     heatmap=heatmap, threshold=24)
    regions = {region['id']: region for region in report['regions']}
    assert not report['layout_issues'], (suffix, report['layout_issues'])
    assert regions['desktop']['changed_pixels'] > 10000, (suffix, regions)
    # Only the menu should appear. Clock ticks may change a few
    # panel glyphs between the two real-time captures.
    assert regions['panel']['changed_pixel_ratio'] < 0.03, (suffix, regions)
    visual_reviews.append({
        'geometry': suffix,
        'reference': before.name,
        'actual': after.name,
        'reference_sha256': hashlib.sha256(before.read_bytes()).hexdigest(),
        'actual_sha256': hashlib.sha256(after.read_bytes()).hexdigest(),
        'heatmap': heatmap.name,
        'heatmap_sha256': hashlib.sha256(heatmap.read_bytes()).hexdigest(),
        'comparison_version': report['comparison_version'],
        'pixel_threshold': report['pixel_threshold'],
        'changed_pixels': report['changed_pixels'],
        'changed_pixel_ratio': report['changed_pixel_ratio'],
        'perceptual_or_functional_accuracy': report['perceptual_or_functional_accuracy'],
        'regions': report['regions'],
        'layout_issues': report['layout_issues'],
    })
(directory / 'luna-menu-visual-review.json').write_text(
    json.dumps({'report_version': 1, 'source_commit': manifest['source_commit'],
                'recipe_sha256': hashlib.sha256(luna_recipe.read_bytes()).hexdigest(),
                'comparisons': visual_reviews}, indent=2, sort_keys=True) + '\n')
manifest['luna_menu_visual_review'] = 'luna-menu-visual-review.json'
for label in ('xp-luna-columns', 'xp-luna-columns-menu', 'xp-luna-font-menu'):
    with Image.open(directory / f'{label}.png') as image:
        # swaybg is a separate process from native RicePlate. A
        # black compositor root is not a faithful Luna screenshot.
        wallpaper_pixel = image.convert('RGB').getpixel((700, 350))
    assert sum(wallpaper_pixel) > 90, (label, 'missing Luna wallpaper', wallpaper_pixel)
for suffix, width, height in (
    ('1024x768', 1024, 768), ('1920x1080', 1920, 1080),
    ('scale-125', 1366, 768),
):
    # The virtual-pointer compositor client clicks the REAL Start
    # button twice. An opt-in --preview-menu capture cannot pass.
    files = [directory / f'xp-luna-pointer-{state}-{suffix}.png'
             for state in ('open', 'closed')]
    reference = directory / f'xp-luna-columns-{suffix}.png'
    with Image.open(files[0]) as opened_image, \
         Image.open(files[1]) as closed_image, \
         Image.open(reference) as initial_image:
        assert opened_image.size == closed_image.size == initial_image.size == \
            (width, height), f'Clicked Luna output geometry mismatch: {suffix}'
        region = (0, height - 450, min(width, 500), height - 50)
        opened = opened_image.convert('RGB').crop(region)
        closed = closed_image.convert('RGB').crop(region)
        initial = initial_image.convert('RGB').crop(region)
        menu_delta = sum(left != right for left, right in
                         zip(opened.getdata(), closed.getdata()))
        restore_delta = sum(left != right for left, right in
                            zip(closed.getdata(), initial.getdata()))
    assert menu_delta > 10000, \
        f'Native Luna Start pointer click did not open/close: {suffix}: {menu_delta}'
    assert restore_delta < 5000, \
        f'Native Luna second pointer click did not restore desktop: {suffix}: {restore_delta}'
    print(f'Native virtual-pointer Luna Start toggle {suffix}: '
          f'{menu_delta} menu pixels, {restore_delta} restore delta')
# The real native Find and Saved header buttons must switch visible
# menu content and return to the same open-menu state. At 1024x768
# the 320x304 logical Luna menu renders as a 400x380 pixel surface,
# anchored immediately above the 40px taskbar. Compare the entire
# compositor-visible menu instead of the obsolete 320px sub-rectangle.
# Checks use real labwc frames, not Rust-only hit tests.
luna_menu_crop = (0, 348, 400, 728)
modes = ('open', 'find', 'saved', 'return')
frames = {}
for mode in modes:
    with Image.open(directory / f'xp-luna-pointer-{mode}-1024x768.png') as image:
        assert image.size == (1024, 768), (mode, image.size)
        frames[mode] = image.convert('RGB').crop(luna_menu_crop)
def changed_pixels(left, right):
    return sum(a != b for a, b in zip(left.getdata(), right.getdata()))
find_delta = changed_pixels(frames['open'], frames['find'])
saved_delta = changed_pixels(frames['open'], frames['saved'])
mode_delta = changed_pixels(frames['find'], frames['saved'])
return_delta = changed_pixels(frames['open'], frames['return'])
# A real click on Luna's left-column All Programs row must open a
# distinct installed-app list; the visible Back control restores
# the existing native two-column menu without launching fuzzel.
with Image.open(directory / 'xp-luna-pointer-programs-1024x768.png') as image, \
     Image.open(directory / 'xp-luna-pointer-programs-back-1024x768.png') as back_image:
    assert image.size == back_image.size == (1024, 768)
    programs = image.convert('RGB').crop(luna_menu_crop)
    programs_back = back_image.convert('RGB').crop(luna_menu_crop)
programs_delta = changed_pixels(frames['return'], programs)
programs_back_delta = changed_pixels(frames['return'], programs_back)
with Image.open(directory / 'xp-luna-pointer-find-paged-1024x768.png') as image, \
     Image.open(directory / 'xp-luna-pointer-find-hover-1024x768.png') as hovered_image:
    assert image.size == hovered_image.size == (1024, 768), 'Wheel capture geometry'
    paged = image.convert('RGB').crop(luna_menu_crop)
    hovered = hovered_image.convert('RGB').crop(luna_menu_crop)
wheel_delta = changed_pixels(hovered, paged)
with Image.open(directory / 'xp-luna-pointer-find-restored-1024x768.png') as image:
    assert image.size == (1024, 768), 'Reverse wheel capture geometry'
    restored = image.convert('RGB').crop(luna_menu_crop)
# The return pointer stays over the scrolled page's selected row;
# hover cannot itself jump back. Negative axis must restore the
# entire original menu, including the active item highlight.
reverse_delta = changed_pixels(paged, restored)
restore_page_delta = changed_pixels(hovered, restored)
# Test right-button pin/unpin through the live compositor. Compare
# only the action rows, excluding transient footer notices, so a
# label or mouse-hover change alone cannot stand in for Saved data.
pin_frames = {}
for state in ('saved', 'saved-pinned', 'saved-unpinned'):
    with Image.open(directory / f'xp-luna-pointer-{state}-1024x768.png') as image:
        assert image.size == (1024, 768), (state, image.size)
        pin_frames[state] = image.convert('RGB').crop((0, 483, 400, 688))
pinned_delta = changed_pixels(pin_frames['saved'], pin_frames['saved-pinned'])
unpin_delta = changed_pixels(pin_frames['saved'], pin_frames['saved-unpinned'])
assert find_delta > 2000, f'Find click had no visible native effect: {find_delta}'
assert saved_delta > 2000, f'Saved click had no visible native effect: {saved_delta}'
assert mode_delta > 500, f'Find and Saved rendered alike: {mode_delta}'
assert wheel_delta > 1200, f'Wayland wheel did not page search results: {wheel_delta}'
assert reverse_delta > 1200, f'Reverse wheel did not change the page: {reverse_delta}'
assert restore_page_delta < 1500, \
    f'Reverse wheel did not restore the original search page: {restore_page_delta}'
assert pinned_delta > 600, \
    f'Right-click did not add a visible Saved action: {pinned_delta}'
assert unpin_delta < 300, \
    f'Right-click did not restore the empty Saved action list: {unpin_delta}'
assert return_delta < 1500, f'Header Back did not restore menu: {return_delta}'
assert programs_delta > 1200, \
    f'All Programs click did not change native Luna menu: {programs_delta}'
assert programs_back_delta < 1500, \
    f'All Programs Back did not restore Luna columns: {programs_back_delta}'
print(f'Native Luna header clicks: Find={find_delta} Saved={saved_delta} '
      f'distinct={mode_delta} wheel={wheel_delta} reverse={reverse_delta} '
      f'page restored={restore_page_delta} pin={pinned_delta} '
      f'unpin={unpin_delta} header restored={return_delta} '
      f'programs={programs_delta} programs back={programs_back_delta} RGB pixels')
# Separate, real RicePop sample inbox: pointer motion is captured
# before the wheel, so hover alone cannot satisfy this assertion.
notification_frames = {}
for state in ('hover', 'paged', 'restored'):
    with Image.open(directory / f'xp-luna-columns-notifications-scroll-{state}.png') as image:
        assert image.size == (1366, 768), (state, image.size)
        notification_frames[state] = image.convert('RGB').crop((0, 424, 320, 728))
ricepop_page_delta = changed_pixels(notification_frames['hover'], notification_frames['paged'])
ricepop_reverse_delta = changed_pixels(notification_frames['paged'], notification_frames['restored'])
ricepop_restore_delta = changed_pixels(notification_frames['hover'], notification_frames['restored'])
assert ricepop_page_delta > 750, f'RicePop Wayland wheel did not page notices: {ricepop_page_delta}'
assert ricepop_reverse_delta > 750, f'RicePop reverse wheel did not change page: {ricepop_reverse_delta}'
assert ricepop_restore_delta < 1500, f'RicePop reverse wheel did not restore page: {ricepop_restore_delta}'
print(f'Native RicePop notification wheel={ricepop_page_delta} '
      f'reverse={ricepop_reverse_delta} restored={ricepop_restore_delta} RGB pixels')
assert captures['calendar-v5'] != captures['desktop-v5'], 'Native calendar did not render in Wayland frame'
with Image.open(directory / 'calendar-v5.png') as image:
    header = image.convert('RGB').getpixel((700, 50))
assert all(abs(actual - expected) <= 2 for actual, expected in
           zip(header, (65, 121, 170))), f'native calendar popup header missing: {header}'
(directory / 'capture-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
PY
