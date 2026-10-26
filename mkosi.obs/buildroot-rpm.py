#!/usr/bin/python3
"""Make an OBS-resolvable RPM from a desktop's already-exported build root."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def release_fields(text):
    """Read os-release as data."""
    fields = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        words = shlex.split(value)
        if not separator or len(words) != 1:
            raise ValueError('Invalid os-release field')
        fields[key] = words[0]
    return fields


def packages(root):
    query = r'%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\t%{ARCH}\n'
    result = subprocess.run(['rpm', '--root', str(root), '--dbpath',
                             '/usr/lib/sysimage/rpm', '-qa', '--qf', query],
                            check=True, capture_output=True, text=True)
    inventory = {}
    for line in result.stdout.splitlines():
        name, version, architecture = line.split('\t')
        inventory[f'{name}.{architecture}'] = version
    if not inventory:
        raise ValueError('Empty base RPM inventory')
    return inventory


def check_release(release, image, version):
    expected = dict(IMAGE_ID=image, IMAGE_VERSION=version,
                    SYSEXT_LEVEL=f'{image}-{version}')
    for key, value in expected.items():
        if release.get(key) != value:
            raise ValueError(f'Base {key} mismatch: expected {value!r}')
    if release.get('ID') in (None, '', '_any'):
        raise ValueError('Base must have a concrete distribution ID')


def build_rpm(root, archive, image, version, architecture, epoch):
    if not re.fullmatch(r'proto-(kde|gnome)', image):
        raise ValueError('Unexpected Proto desktop identity')
    if not re.fullmatch(r'[0-9][a-z0-9.]*', version):
        raise ValueError('Version must be usable unchanged as an RPM Version')
    rpm_arch = {'x86-64': 'x86_64', 'arm64': 'aarch64', 'ppc64-le': 'ppc64le',
                'ppc64': 'ppc64', 's390x': 's390x', 'riscv64': 'riscv64',
                'arm': 'armv7hl'}[architecture]
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    release = release_fields((root / 'usr/lib/os-release').read_text())
    check_release(release, image, version)
    descriptor = dict(format=1, image=image, version=version, architecture=architecture,
                      distribution='opensuse', distribution_release='tumbleweed',
                      filename=archive.name, sha256=digest, release=release,
                      packages=packages(root))
    with tempfile.TemporaryDirectory(prefix='proto-buildroot-rpm-', dir=archive.parent) as directory:
        work = Path(directory)
        metadata = work / f'{image}.json'
        metadata.write_text(json.dumps(descriptor, sort_keys=True) + '\n')
        spec = work / 'buildroot.spec'
        spec.write_text(f'''Name: {image}-buildroot
Version: {version}
Release: 1.{epoch}
Summary: Exact {image} build root for system extensions
License: MIT
# This RPM transports a filesystem archive; its contained RPM database is not
# the worker's installed package database. Do not generate runtime dependencies.
AutoReqProv: no
%description
Versioned filesystem archive and compatibility/RPM-inventory metadata for
offline mkosi system extension builds. Not intended for installation on Proto.
%prep
%build
%install
mkdir -p %{{buildroot}}%{{_datadir}}/sysext-buildroots
cp --reflink=auto '{archive}' %{{buildroot}}%{{_datadir}}/sysext-buildroots/
cp '{metadata}' %{{buildroot}}%{{_datadir}}/sysext-buildroots/
%files
%dir %{{_datadir}}/sysext-buildroots
%{{_datadir}}/sysext-buildroots/{archive.name}
%{{_datadir}}/sysext-buildroots/{metadata.name}
%changelog
''')
        # Already XZ-compressed: do not spend CPU recompressing the RPM payload.
        # Disable distribution BRP helpers: payload is opaque, not another host.
        subprocess.run(['rpmbuild', '-bb', str(spec), '--target', rpm_arch,
                        '--define', f'_topdir {work}',
                        '--define', f'_rpmdir {archive.parent}',
                        '--define', '_rpmfilename %{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm',
                        '--define', '_binary_payload w0.gzdio',
                        '--define', '__os_install_post %{nil}',
                        '--define', '_build_id_links none',
                        '--define', 'debug_package %{nil}'],
                       env=dict(os.environ, SOURCE_DATE_EPOCH=str(epoch)), check=True)


def main():
    image, version, architecture = (os.environ[k] for k in ('IMAGE_ID', 'IMAGE_VERSION', 'ARCHITECTURE'))
    archive = Path(os.environ['OUTPUTDIR']) / f'{image}_{version}_{architecture}.buildroot.tar.xz'
    build_rpm(Path(str(archive).removesuffix('.tar.xz')), archive, image, version,
              architecture, int(os.environ['SOURCE_DATE_EPOCH']))


if __name__ == '__main__':
    main()
