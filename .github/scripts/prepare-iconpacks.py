import logging
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
LOGGER = logging.getLogger(__name__)

ICONPACKS_DIR = './iconpacks'
RES_DIR = './app/src/main/res'
ARRAYS_FILE = os.path.join(RES_DIR, 'values', 'arrays.xml')
MANIFEST_FILE = './app/src/main/AndroidManifest.xml'

VALID_FILE_EXTENSIONS = ('.xml', '.png', '.jpg', '.jpeg', '.webp', '.9.png')
FILE_TYPES = ('drawable', 'anim', 'animator', 'interpolator', 'color', 'mipmap')
VALUE_TYPES = ('color', 'dimen', 'integer', 'bool', 'fraction')
REFERENCE = re.compile(r'@(drawable|anim|animator|interpolator|color|mipmap|dimen|integer|bool|fraction)/([A-Za-z0-9_]+)')

OS17_VARIANTS = {
    'com.android.systemui': {
        *[f'stat_signal_wifi_signal_{i}' for i in range(5)],
        'stat_signal_wifi_double',
        'stat_signal_activity_wifi_in',
        'stat_signal_activity_wifi_inout',
        'stat_signal_activity_wifi_none',
        'stat_signal_activity_wifi_out',
        *[f'stat_signal_signal_lte_single_{i}' for i in range(5)],
        'stat_signal_single_novoice_0',
        *[f'stat_signal_signal_novoice_{i}' for i in range(1, 5)],
        *[f'stat_signal_soft_signal_{i}' for i in range(5)],
        'stat_signal_noservice_lte',
        'stat_signal_soft_noservice',
        'stat_signal_activity_default_public',
        'stat_signal_activity_in_public',
        'stat_signal_activity_out_public',
        'stat_signal_activity_inout_public',
        'stat_signal_activity_soft_default_public',
        'stat_signal_activity_soft_in_public',
        'stat_signal_activity_soft_out_public',
        'stat_signal_activity_soft_inout_public',
    },
}

PACKAGE_ALIASES = {
    'com.android.systemui': 'systemui',
    'com.android.settings': 'settings',
}


def slug(text):
    return re.sub(r'[^a-z0-9]', '_', text.lower())


def split_name(file_name):
    if file_name.lower().endswith('.9.png'):
        return file_name[:-6], '.9.png'
    base, ext = os.path.splitext(file_name)
    return base, ext.lower()


def folder_type(folder):
    return folder.split('-')[0]


def get_icon_packs():
    if not os.path.isdir(ICONPACKS_DIR):
        LOGGER.error("Icon packs folder not found: %s", ICONPACKS_DIR)
        sys.exit(1)
    packs = sorted(f for f in os.listdir(ICONPACKS_DIR) if os.path.isdir(os.path.join(ICONPACKS_DIR, f)))
    LOGGER.info("Found %d icon packs", len(packs))
    return packs


def read_package(package_path):
    files = []
    values = []
    for entry in sorted(os.listdir(package_path)):
        path = os.path.join(package_path, entry)
        if os.path.isfile(path):
            base, ext = split_name(entry)
            if ext in VALID_FILE_EXTENSIONS:
                files.append(('drawable', base, ext, path))
        elif os.path.isdir(path):
            ftype = folder_type(entry)
            if ftype in FILE_TYPES:
                for f in sorted(os.listdir(path)):
                    base, ext = split_name(f)
                    if ext in VALID_FILE_EXTENSIONS:
                        files.append((entry, base, ext, os.path.join(path, f)))
            elif ftype == 'values':
                for f in sorted(os.listdir(path)):
                    if not f.endswith('.xml'):
                        continue
                    root = ET.parse(os.path.join(path, f)).getroot()
                    for el in root:
                        rtype = el.get('type') if el.tag == 'item' else el.tag
                        if rtype in VALUE_TYPES and el.get('name'):
                            values.append((entry, rtype, el))
    return files, values


def rewrite(text, provided, suffix):
    def replace(match):
        rtype, name = match.group(1), match.group(2)
        if name in provided.get(rtype, set()):
            return f'@{rtype}/{name}{suffix}'
        return match.group(0)

    return REFERENCE.sub(replace, text)


def process():
    mappings_by_pack = {}
    for pack_name in get_icon_packs():
        pack_slug = slug(pack_name)
        pack_path = os.path.join(ICONPACKS_DIR, pack_name)
        mappings = []
        for package_name in sorted(os.listdir(pack_path)):
            package_path = os.path.join(pack_path, package_name)
            if not os.path.isdir(package_path):
                continue
            alias = slug(PACKAGE_ALIASES.get(package_name, package_name))
            suffix = f'_{alias}_{pack_slug}'
            files, values = read_package(package_path)

            provided = {}
            for folder, base, _, _ in files:
                provided.setdefault(folder_type(folder), set()).add(base)
            for _, rtype, el in values:
                provided.setdefault(rtype, set()).add(el.get('name'))

            for folder, base, ext, path in files:
                dest_dir = os.path.join(RES_DIR, folder)
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, f'{base}{suffix}{ext}')
                if ext == '.xml':
                    with open(path, encoding='utf-8') as f:
                        content = f.read()
                    with open(dest, 'w', encoding='utf-8', newline='\n') as f:
                        f.write(rewrite(content, provided, suffix))
                else:
                    shutil.copy(path, dest)

            by_folder = {}
            for folder, rtype, el in values:
                by_folder.setdefault(folder, []).append(el)
            for folder, elements in by_folder.items():
                dest_dir = os.path.join(RES_DIR, folder)
                os.makedirs(dest_dir, exist_ok=True)
                lines = []
                for el in elements:
                    el.set('name', el.get('name') + suffix)
                    el.tail = None
                    lines.append('    ' + rewrite(ET.tostring(el, encoding='unicode').strip(), provided, suffix))
                with open(os.path.join(dest_dir, f'iconpack{suffix}.xml'), 'w', encoding='utf-8', newline='\n') as f:
                    f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n' + '\n'.join(lines) + '\n</resources>\n')

            drawables = sorted({base for folder, base, _, _ in files if folder_type(folder) == 'drawable'})
            for base in drawables:
                mappings.append((f'{package_name}:{base}', f'{base}{suffix}'))
                if base in OS17_VARIANTS.get(package_name, set()):
                    mappings.append((f'{package_name}:{base}_os17', f'{base}{suffix}'))
            LOGGER.info("%s [%s]: %d files, %d values, %d icons", pack_name, package_name, len(files), len(values), len(drawables))
        mappings_by_pack[pack_name] = mappings
    return mappings_by_pack


def update_manifest(packs):
    with open(MANIFEST_FILE, encoding='utf-8') as f:
        manifest = f.read()
    start_comment = '<!-- START OF ICON PACKS -->'
    end_comment = '<!-- END OF ICON PACKS -->'
    start = manifest.find(start_comment)
    end = manifest.find(end_comment)
    if start == -1 or end == -1:
        LOGGER.error("Comment markers not found in manifest file")
        sys.exit(1)
    activities = ''
    for pack_name in packs:
        activities += f"""
        <activity android:name="{slug(pack_name)}"
            android:label="{pack_name}"
            android:exported="true">
            <intent-filter>
                <action android:name="it.dhd.oxygencustomizer.iconpack" />
                <category android:name="android.intent.category.DEFAULT" />
            </intent-filter>
        </activity>
"""
    with open(MANIFEST_FILE, 'w', encoding='utf-8', newline='\n') as f:
        f.write(manifest[:start + len(start_comment)] + activities + '\n        ' + manifest[end:])


def write_arrays(mappings_by_pack):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<resources>']
    for pack_name, mappings in mappings_by_pack.items():
        pack_slug = slug(pack_name)
        lines.append(f'    <string-array name="{pack_slug}" translatable="false">')
        lines.append(f'        <item>mapping_source_{pack_slug}</item>')
        lines.append(f'        <item>replacement_{pack_slug}</item>')
        lines.append('    </string-array>')
        lines.append(f'    <string-array name="mapping_source_{pack_slug}" translatable="false">')
        lines.extend(f'        <item>{source}</item>' for source, _ in mappings)
        lines.append('    </string-array>')
        lines.append(f'    <string-array name="replacement_{pack_slug}" translatable="false">')
        lines.extend(f'        <item>{replacement}</item>' for _, replacement in mappings)
        lines.append('    </string-array>')
    lines.append('</resources>')
    os.makedirs(os.path.dirname(ARRAYS_FILE), exist_ok=True)
    with open(ARRAYS_FILE, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    mappings_by_pack = process()
    update_manifest(list(mappings_by_pack.keys()))
    write_arrays(mappings_by_pack)
    LOGGER.info("Done")


if __name__ == '__main__':
    main()
