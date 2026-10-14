#!/usr/bin/env python3
"""ifinmail Android release tool: version, sign, build, verify and publish over the air.

Standard library only; works on Windows, macOS and Linux.

    release.py status                       where things stand (local version, key, server)
    release.py keygen                       create the release signing key (once, then back it up)
    release.py bump minor|major|patch|X.Y.Z raise the version in gradle.properties
    release.py notes                        draft release notes from the commits since the last release
    release.py build [--version X.Y.Z]      signed, minified release APK in dist/, verified
    release.py verify dist/app.apk          check an APK the way the server and the phone will
    release.py publish dist/app.apk         upload it (checks first; --dry-run only checks)
    release.py release --version X.Y.Z      build + verify + publish in one go
    release.py tag                          git-tag the current version (android-vX.Y.Z)

Environment: IFINMAIL_API_TOKEN (API key with scope system.manage), IFINMAIL_SERVER (defaults to
ifinmail.updateBaseUrl), signing from keystore.properties or IFINMAIL_KEYSTORE_FILE /
IFINMAIL_KEYSTORE_PASSWORD / IFINMAIL_KEY_ALIAS / IFINMAIL_KEY_PASSWORD, IFINMAIL_GRADLE to use a
different Gradle than ./gradlew.

versionCode is derived from the version name (MAJOR*10000 + MINOR*100 + PATCH), so it always rises
with the version and two people can never pick the same number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # clients/android
REPO = ROOT.parent.parent
PROPS = ROOT / 'gradle.properties'
DIST = ROOT / 'dist'
PACKAGE = 'com.ifinmail'
APK_TYPE = 'application/vnd.android.package-archive'
DEFAULT_KEYSTORE = Path.home() / '.ifinmail' / 'android' / 'ifinmail-release.jks'
VERSION_RE = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{1,2})$')


class ToolError(Exception):
    """A problem to report in one line, without a traceback."""


# ----------------------------------------------------------------------------- versions

def parse_version(text: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(text.strip())
    if not match:
        # "1.0" (the original gradle.properties value) is read as 1.0.0.
        short = re.match(r'^(\d{1,2})\.(\d{1,2})$', text.strip())
        if not short:
            raise ToolError(f'"{text}" is not a version like 1.4.2 (each part 0-99).')
        return int(short[1]), int(short[2]), 0
    return int(match[1]), int(match[2]), int(match[3])


def version_code(version: tuple[int, int, int]) -> int:
    major, minor, patch = version
    return major * 10000 + minor * 100 + patch


def version_name(version: tuple[int, int, int]) -> str:
    return '.'.join(str(p) for p in version)


def read_props() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in PROPS.read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            out[key.strip()] = value.strip()
    return out


def set_prop(key: str, value: str) -> None:
    raw = PROPS.read_bytes().decode('utf-8')
    eol = '\r\n' if '\r\n' in raw else '\n'
    pattern = re.compile(rf'^{re.escape(key)}[ \t]*=[^\r\n]*', re.MULTILINE)
    if pattern.search(raw):
        raw = pattern.sub(lambda _m: f'{key}={value}', raw, count=1)
    else:
        raw = raw.rstrip('\r\n') + eol + f'{key}={value}' + eol
    PROPS.write_bytes(raw.encode('utf-8'))


def current_version() -> tuple[int, int, int]:
    return parse_version(read_props().get('ifinmail.versionName', '1.0'))


# ----------------------------------------------------------------------------- SDK + signing

def sdk_dir() -> Path:
    for var in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.environ.get(var):
            return Path(os.environ[var])
    local = ROOT / 'local.properties'
    if local.is_file():
        for line in local.read_text(encoding='utf-8').splitlines():
            if line.startswith('sdk.dir='):
                return Path(line.split('=', 1)[1].replace('\\:', ':').replace('\\\\', '\\'))
    raise ToolError('Android SDK not found: set ANDROID_HOME or sdk.dir in local.properties.')


def build_tool(name: str) -> str:
    base = sdk_dir() / 'build-tools'
    candidates = sorted(base.glob('*'), key=lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r'\D+', p.name)])
    suffixes = ['.bat', '.exe', ''] if os.name == 'nt' else ['', '.bat']
    for folder in reversed(candidates):
        for suffix in suffixes:
            candidate = folder / f'{name}{suffix}'
            if candidate.is_file():
                return str(candidate)
    raise ToolError(f'{name} not found under {base}; install Android build-tools.')


def signing_env() -> dict[str, str]:
    """Signing values from the environment, else keystore.properties, as IFINMAIL_* variables."""
    env = {k: os.environ[k] for k in (
        'IFINMAIL_KEYSTORE_FILE', 'IFINMAIL_KEYSTORE_PASSWORD', 'IFINMAIL_KEY_ALIAS', 'IFINMAIL_KEY_PASSWORD',
    ) if os.environ.get(k)}
    if len(env) == 4:
        return env
    file = ROOT / 'keystore.properties'
    if file.is_file():
        values = dict(
            line.split('=', 1) for line in file.read_text(encoding='utf-8').splitlines()
            if '=' in line and not line.startswith('#')
        )
        if all(values.get(k) for k in ('storeFile', 'storePassword', 'keyAlias', 'keyPassword')):
            return {}  # gradle reads the file itself
    raise ToolError('No signing key configured. Run "release.py keygen" or set IFINMAIL_KEYSTORE_*.')


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, quiet: bool = False) -> str:
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=quiet, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()[-1500:]
        raise ToolError(f'{Path(cmd[0]).name} failed ({result.returncode}). {detail}')
    return result.stdout if quiet else ''


# ----------------------------------------------------------------------------- APK facts

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(apk: Path) -> dict[str, object]:
    """Package, version, minSdk and the signing certificate, read with the platform's own tools."""
    if not apk.is_file():
        raise ToolError(f'{apk} is not a file.')
    badging = run([build_tool('aapt2'), 'dump', 'badging', str(apk)], quiet=True)
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging)
    if not package:
        raise ToolError('Could not read the package from the APK.')
    min_sdk = re.search(r"minSdkVersion:'(\d+)'", badging)
    certs = run([build_tool('apksigner'), 'verify', '--verbose', '--print-certs', str(apk)], quiet=True)
    cert = re.search(r'certificate SHA-256 digest: ([0-9a-f]{64})', certs)
    schemes = re.findall(r'Verified using (v\d(?:\.\d)?) scheme[^:]*: true', certs)
    return {
        'package': package[1],
        'version_code': int(package[2]),
        'version_name': package[3],
        'min_sdk': int(min_sdk[1]) if min_sdk else 0,
        'cert_sha256': cert[1] if cert else '',
        'schemes': schemes,
        'sha256': sha256_of(apk),
        'size': apk.stat().st_size,
    }


def check_facts(facts: dict[str, object]) -> None:
    if facts['package'] != PACKAGE:
        raise ToolError(f'Package is {facts["package"]}, expected {PACKAGE}.')
    if not facts['cert_sha256'] or not facts['schemes']:
        raise ToolError('The APK is not signed with a v2+ signature; devices will not install it.')
    if 'debug' in str(facts['version_name']).lower():
        raise ToolError('This looks like a debug build.')


def describe(facts: dict[str, object]) -> str:
    return (
        f"  {facts['package']} {facts['version_name']} (build {facts['version_code']}), minSdk {facts['min_sdk']}\n"
        f"  signed {'/'.join(facts['schemes'])}  cert {str(facts['cert_sha256'])[:16]}...\n"  # type: ignore[arg-type]
        f"  {int(facts['size']) / 1048576:.1f} MB  sha256 {facts['sha256']}"  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------------- server

def server_url(args: argparse.Namespace) -> str:
    url = (getattr(args, 'server', None) or os.environ.get('IFINMAIL_SERVER')
           or read_props().get('ifinmail.updateBaseUrl', '')).rstrip('/')
    local = re.match(r'^http://(localhost|127\.0\.0\.1)(:\d+)?$', url)  # a dev server on this machine
    if not url.startswith('https://') and not local:
        raise ToolError(f'The server must be an https:// address (got "{url or "nothing"}"). Use --server.')
    return url


def api(method: str, url: str, token: str, body: bytes | None = None, content_type: str | None = None) -> object:
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header('Authorization', f'Bearer {token}')
    request.add_header('Accept', 'application/json')
    if content_type:
        request.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as err:
        text = err.read().decode('utf-8', 'replace')[:600]
        try:
            text = json.loads(text).get('detail', text)
        except ValueError:
            pass
        raise ToolError(f'Server said {err.code}: {text}') from err
    except urllib.error.URLError as err:
        raise ToolError(f'Could not reach {url}: {err.reason}') from err


def token() -> str:
    value = os.environ.get('IFINMAIL_API_TOKEN', '').strip()
    if not value:
        raise ToolError('Set IFINMAIL_API_TOKEN to an API key with the system.manage scope.')
    return value


def server_releases(args: argparse.Namespace) -> list[dict[str, object]]:
    data = api('GET', f'{server_url(args)}/api/v1/releases/android', token())
    return list(data.get('releases', data) if isinstance(data, dict) else data)  # type: ignore[union-attr]


def multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8')
        )
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
         f'Content-Type: {APK_TYPE}\r\n\r\n').encode('utf-8')
    )
    parts.append(path.read_bytes())
    parts.append(f'\r\n--{boundary}--\r\n'.encode('utf-8'))
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


# ----------------------------------------------------------------------------- commands

def cmd_status(args: argparse.Namespace) -> None:
    props = read_props()
    version = current_version()
    print(f'Local version : {version_name(version)} (build {version_code(version)})')
    print(f'Channel       : {props.get("ifinmail.updateChannel", "stable")}')
    print(f'Update server : {props.get("ifinmail.updateBaseUrl", "(none)")}')
    try:
        signing_env()
        print('Signing key   : configured')
    except ToolError:
        print('Signing key   : not configured (release.py keygen)')
    if os.environ.get('IFINMAIL_API_TOKEN'):
        try:
            for r in server_releases(args):
                state = 'live' if r.get('is_published') else 'withdrawn'
                print(f'  server: {r["version_name"]:<10} build {r["version_code"]:<7} {r["channel"]:<7} {state}')
        except ToolError as err:
            print(f'Server        : {err}')
    else:
        print('Server        : set IFINMAIL_API_TOKEN to list releases')


def cmd_keygen(args: argparse.Namespace) -> None:
    store = Path(args.keystore).expanduser()
    target = ROOT / 'keystore.properties'
    if store.exists() or target.exists():
        raise ToolError(f'{store if store.exists() else target} already exists; refusing to replace a release key.')
    keytool = shutil.which('keytool') or (
        str(Path(os.environ['JAVA_HOME']) / 'bin' / 'keytool') if os.environ.get('JAVA_HOME') else None)
    if not keytool:
        raise ToolError('keytool not found; install a JDK (17+) or set JAVA_HOME.')
    store.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    alias = 'ifinmail'
    run([keytool, '-genkeypair', '-keystore', str(store), '-alias', alias, '-keyalg', 'RSA', '-keysize', '4096',
         '-validity', '10000', '-storepass', password, '-keypass', password,
         '-dname', args.dname], quiet=True)
    target.write_text(
        '# Written by release.py keygen. Git-ignored. Back up the .jks AND this password.\n'
        f'storeFile={store.as_posix()}\nstorePassword={password}\nkeyAlias={alias}\nkeyPassword={password}\n',
        encoding='utf-8',
    )
    try:
        os.chmod(store, 0o600)
        os.chmod(target, 0o600)
    except OSError:
        pass
    print(f'Created {store}\nWrote   {target}  (git-ignored)\n')
    print('BACK THIS UP NOW (password manager or offline vault): the .jks file and the password in')
    print('keystore.properties. Without them no installed app can ever be updated again, and devices')
    print('refuse an update signed with a different key.')


def cmd_bump(args: argparse.Namespace) -> None:
    major, minor, patch = current_version()
    target = args.to
    if target == 'major':
        new = (major + 1, 0, 0)
    elif target == 'minor':
        new = (major, minor + 1, 0)
    elif target == 'patch':
        new = (major, minor, patch + 1)
    else:
        new = parse_version(target)
    if version_code(new) <= version_code((major, minor, patch)):
        raise ToolError(f'{version_name(new)} is not higher than {version_name((major, minor, patch))}.')
    set_prop('ifinmail.versionName', version_name(new))
    set_prop('ifinmail.versionCode', str(version_code(new)))
    print(f'{version_name((major, minor, patch))} -> {version_name(new)} (build {version_code(new)})')
    print('Review gradle.properties and commit it with the release notes.')


def cmd_notes(args: argparse.Namespace) -> None:
    version = version_name(current_version())
    tags = run(['git', 'tag', '--list', 'android-v*', '--sort=-v:refname'], cwd=REPO, quiet=True).split()
    since = f'{tags[0]}..HEAD' if tags else 'HEAD'
    log = run(['git', 'log', since, '--no-merges', '--pretty=format:%s', '--', 'clients/android', 'backend/apps/core/releases'],
              cwd=REPO, quiet=True)
    lines = [l.strip() for l in log.splitlines() if l.strip() and not re.match(r'^v\d+\.\d+\.\d+$', l.strip())]
    out = Path(args.out) if args.out else ROOT / 'release-notes' / f'{version}.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    body = '\n'.join(f'- {l}' for l in lines) or '- Maintenance and polish.'
    out.write_text(f'## What is new in {version}\n\n{body}\n', encoding='utf-8')
    print(f'Drafted {out} from {len(lines)} commit(s) since {tags[0] if tags else "the start"}. Edit it, then publish with --notes-file.')


def build(version: tuple[int, int, int], channel: str | None, server: str | None) -> Path:
    signing_env()
    gradle = os.environ.get('IFINMAIL_GRADLE') or str(ROOT / ('gradlew.bat' if os.name == 'nt' else 'gradlew'))
    flags = [f'-Pifinmail.versionCode={version_code(version)}', f'-Pifinmail.versionName={version_name(version)}']
    if channel:
        flags.append(f'-Pifinmail.updateChannel={channel}')
    if server:
        flags.append(f'-Pifinmail.updateBaseUrl={server}')
    print(f'Building {version_name(version)} (build {version_code(version)})...')
    run([gradle, ':app:androidApp:assembleRelease', '--console=plain', '-q', *flags], cwd=ROOT, env=signing_env())
    built = ROOT / 'app' / 'androidApp' / 'build' / 'outputs' / 'apk' / 'release'
    signed = built / 'androidApp-release.apk'
    if not signed.is_file():
        raise ToolError('Gradle produced no signed APK (only an unsigned one). Check the signing key.')
    DIST.mkdir(exist_ok=True)
    out = DIST / f'ifinmail-{version_name(version)}-{version_code(version)}.apk'
    shutil.copy2(signed, out)
    return out


def finish_build(apk: Path, version: tuple[int, int, int]) -> dict[str, object]:
    facts = inspect(apk)
    check_facts(facts)
    if facts['version_code'] != version_code(version):
        raise ToolError(f'APK says build {facts["version_code"]}, expected {version_code(version)}.')
    (apk.with_suffix('.apk.sha256')).write_text(f'{facts["sha256"]}  {apk.name}\n', encoding='utf-8')
    print(f'Built {apk}\n{describe(facts)}')
    return facts


def cmd_build(args: argparse.Namespace) -> None:
    version = parse_version(args.version) if args.version else current_version()
    apk = build(version, args.channel, getattr(args, 'server', None) or None)
    finish_build(apk, version)


def cmd_verify(args: argparse.Namespace) -> None:
    facts = inspect(Path(args.apk))
    check_facts(facts)
    print(describe(facts))
    if os.environ.get('IFINMAIL_API_TOKEN'):
        preflight(args, facts)
    print('OK')


def preflight(args: argparse.Namespace, facts: dict[str, object]) -> None:
    """What the server will refuse, found before uploading 20 MB."""
    channel = getattr(args, 'channel', None) or 'stable'
    existing = [r for r in server_releases(args) if r.get('channel') == channel]
    if any(r['version_code'] == facts['version_code'] for r in existing):
        raise ToolError(f'Build {facts["version_code"]} is already on the {channel} channel.')
    newest = max((int(r['version_code']) for r in existing), default=0)  # type: ignore[arg-type]
    if int(facts['version_code']) < newest:  # type: ignore[arg-type]
        raise ToolError(f'Build {facts["version_code"]} is lower than {newest}, already on {channel}.')
    certs = {r.get('signing_cert_sha256') for r in existing if r.get('signing_cert_sha256')}
    if certs and facts['cert_sha256'] not in certs:
        raise ToolError('Signed with a different key than earlier releases; devices would refuse this update.')
    print(f'  server check: build {facts["version_code"]} is new on {channel} and the signing key matches.')


def cmd_publish(args: argparse.Namespace) -> None:
    apk = Path(args.apk)
    facts = inspect(apk)
    check_facts(facts)
    if args.mandatory and not args.yes and not args.dry_run:
        raise ToolError('--mandatory blocks every older install until it updates; add --yes to confirm.')
    print(describe(facts))
    preflight(args, facts)
    if args.dry_run:
        print('Dry run: nothing uploaded.')
        return
    notes = Path(args.notes_file).read_text(encoding='utf-8') if args.notes_file else args.notes
    fields = {
        'channel': args.channel, 'notes': notes, 'rollout_percent': str(args.rollout),
        'mandatory': 'true' if args.mandatory else 'false', 'publish': 'false' if args.no_publish else 'true',
    }
    body, ctype = multipart(fields, 'file', apk)
    base = server_url(args)
    print(f'Uploading to {base} ({args.channel}, {args.rollout}%)...')
    created = api('POST', f'{base}/api/v1/releases/android', token(), body, ctype)
    print(f'Published {created.get("version_name")} (build {created.get("version_code")}).')  # type: ignore[union-attr]
    if not args.no_publish and args.channel == 'stable' and args.rollout == 100:
        confirm_manifest(base, facts)


def confirm_manifest(base: str, facts: dict[str, object]) -> None:
    """What a device would be told right now, compared with the file that was uploaded."""
    url = f'{base}/updates/v1/android/latest.json?channel=stable&version_code=0'
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            manifest = json.loads(response.read())
    except (urllib.error.URLError, ValueError) as err:
        print(f'  could not read the manifest to confirm: {err}')
        return
    release = manifest.get('latest') or {}
    if release.get('sha256') == facts['sha256']:
        print(f'  manifest confirms sha256 {facts["sha256"][:16]}... for build {release.get("version_code")}')  # type: ignore[index]
    else:
        print('  WARNING: the manifest does not (yet) point at this file; check the console.')


def cmd_release(args: argparse.Namespace) -> None:
    version = parse_version(args.version)
    apk = build(version, args.channel, getattr(args, 'server', None) or None)
    finish_build(apk, version)
    args.apk = str(apk)
    cmd_publish(args)


def cmd_tag(_: argparse.Namespace) -> None:
    name = f'android-v{version_name(current_version())}'
    run(['git', 'tag', '-a', name, '-m', f'Android {version_name(current_version())}'], cwd=REPO)
    print(f'Tagged {name} (push it with: git push origin {name})')


# ----------------------------------------------------------------------------- CLI

def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument('--server', help='https://your-server (default: ifinmail.updateBaseUrl)')
        p.add_argument('--channel', default='stable', choices=['stable', 'beta'])

    def publishing(p: argparse.ArgumentParser) -> None:
        common(p)
        p.add_argument('--notes', default='', help='What is new (Markdown).')
        p.add_argument('--notes-file', help='Read the notes from a file.')
        p.add_argument('--rollout', type=int, default=100, choices=range(0, 101), metavar='0-100')
        p.add_argument('--mandatory', action='store_true')
        p.add_argument('--yes', action='store_true', help='Confirm a mandatory release.')
        p.add_argument('--no-publish', action='store_true', help='Upload but do not offer it yet.')
        p.add_argument('--dry-run', action='store_true', help='Check only; upload nothing.')

    p = sub.add_parser('status', help='local version, key and server state'); common(p); p.set_defaults(fn=cmd_status)
    p = sub.add_parser('keygen', help='create the release signing key')
    p.add_argument('--keystore', default=str(DEFAULT_KEYSTORE))
    p.add_argument('--dname', default='CN=ifinmail, O=ifinmail, C=KE')
    p.set_defaults(fn=cmd_keygen)
    p = sub.add_parser('bump', help='raise the version'); p.add_argument('to', help='major | minor | patch | X.Y.Z')
    p.set_defaults(fn=cmd_bump)
    p = sub.add_parser('notes', help='draft release notes'); p.add_argument('--out'); p.set_defaults(fn=cmd_notes)
    p = sub.add_parser('build', help='signed release APK in dist/'); common(p); p.add_argument('--version')
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser('verify', help='check an APK'); common(p); p.add_argument('apk'); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser('publish', help='upload an APK'); publishing(p); p.add_argument('apk')
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser('release', help='build, verify and publish'); publishing(p)
    p.add_argument('--version', required=True)
    p.set_defaults(fn=cmd_release)
    p = sub.add_parser('tag', help='git-tag the current version'); p.set_defaults(fn=cmd_tag)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        args.fn(args)
    except ToolError as err:
        print(f'error: {err}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
