#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PACKAGE_NAME="kylin-memoryhub"
if [[ -n "${MEMORYHUB_PACKAGE_VERSION:-}" ]]; then
    VERSION="$MEMORYHUB_PACKAGE_VERSION"
else
    VERSION="$(python3 -c 'import pathlib, tomllib, sys; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["project"]["version"])' "$PROJECT_ROOT/pyproject.toml")"
fi
REVISION="${MEMORYHUB_PACKAGE_REVISION:-1}"
ARCH="${MEMORYHUB_PACKAGE_ARCH:-$(dpkg --print-architecture)}"
BUILD_ROOT="$SCRIPT_DIR/build"
DIST_DIR="$SCRIPT_DIR/dist"
STAGE="$BUILD_ROOT/${PACKAGE_NAME}_${VERSION}-${REVISION}_${ARCH}"
WHEELHOUSE="$STAGE/usr/share/memoryhub/wheelhouse"
BUILD_VENV="$BUILD_ROOT/build-venv"
CLIENT_BUILD="$BUILD_ROOT/desktop-client"
OUTPUT="$DIST_DIR/${PACKAGE_NAME}_${VERSION}-${REVISION}_${ARCH}.deb"

test -n "$VERSION" || { echo "Package version is empty" >&2; exit 2; }

case "$BUILD_ROOT" in
    "$PROJECT_ROOT"/packaging/linux/build) ;;
    *) echo "Refusing unsafe build directory: $BUILD_ROOT" >&2; exit 2 ;;
esac

for command in python3 cmake dpkg dpkg-deb sed find install; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing build command: $command" >&2
        exit 2
    }
done

for resource in \
    "$PROJECT_ROOT/memoryhub/safety_rules/data/__init__.py" \
    "$PROJECT_ROOT/memoryhub/safety_rules/data/catalog.json" \
    "$PROJECT_ROOT/memoryhub/safety_rules/data/builtin-1.0.json"; do
    test -f "$resource" || { echo "Missing packaged resource: $resource" >&2; exit 2; }
done

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$DIST_DIR" "$STAGE/DEBIAN" "$WHEELHOUSE"

echo "[1/5] Building Python wheels"
python3 -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/python" -m pip install --upgrade pip wheel setuptools
"$BUILD_VENV/bin/python" -m pip wheel --wheel-dir "$WHEELHOUSE" "$PROJECT_ROOT"
project_wheel="$(find "$WHEELHOUSE" -maxdepth 1 -name 'kylin_memoryhub-*.whl' -print -quit)"
"$BUILD_VENV/bin/python" -c 'import sys, zipfile; required={"memoryhub/safety_rules/data/__init__.py", "memoryhub/safety_rules/data/catalog.json", "memoryhub/safety_rules/data/builtin-1.0.json"}; names=set(zipfile.ZipFile(sys.argv[1]).namelist()); missing=required-names; assert not missing, f"wheel missing resources: {sorted(missing)}"' "$project_wheel"

echo "[2/5] Building Qt desktop client"
cmake -S "$PROJECT_ROOT/desktop-client" -B "$CLIENT_BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$CLIENT_BUILD" --parallel "$(nproc)"
if command -v /usr/sbin/kyexectl >/dev/null 2>&1; then
    echo "Registering freshly built executables with Kylin execution control"
    sudo /usr/sbin/kyexectl -s "$CLIENT_BUILD/memoryhub-client-api-tests"
    sudo /usr/sbin/kyexectl -s "$CLIENT_BUILD/memoryhub-client"
    if command -v /usr/sbin/kysec_netctl >/dev/null 2>&1; then
        sudo /usr/sbin/kysec_netctl --remove -a "$CLIENT_BUILD/memoryhub-client-api-tests" >/dev/null 2>&1 || true
        sudo /usr/sbin/kysec_netctl --remove -a "$CLIENT_BUILD/memoryhub-client" >/dev/null 2>&1 || true
        sudo /usr/sbin/kysec_netctl --set -a "$CLIENT_BUILD/memoryhub-client-api-tests" -s allow
        sudo /usr/sbin/kysec_netctl --set -a "$CLIENT_BUILD/memoryhub-client" -s allow
    fi
fi
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
    QT_QPA_PLATFORM=offscreen ctest --test-dir "$CLIENT_BUILD" --output-on-failure \
    --timeout 30

echo "[3/5] Staging package"
install -d "$STAGE/opt/memoryhub" \
    "$STAGE/etc/memoryhub" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/lib/memoryhub" \
    "$STAGE/usr/lib/systemd/user" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/memoryhub/opencode" \
    "$STAGE/etc/xdg/autostart" \
    "$STAGE/usr/share/doc/$PACKAGE_NAME"

install -m 0755 "$CLIENT_BUILD/memoryhub-client" "$STAGE/usr/bin/memoryhub-client"
install -m 0755 "$SCRIPT_DIR/assets/prepare-user" "$STAGE/usr/lib/memoryhub/prepare-user"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-mcp" "$STAGE/usr/bin/memoryhub-mcp"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-configure-opencode" "$STAGE/usr/bin/memoryhub-configure-opencode"
install -m 0644 "$SCRIPT_DIR/assets/memoryhub.service" "$STAGE/usr/lib/systemd/user/memoryhub.service"
install -m 0644 "$SCRIPT_DIR/assets/config.yaml" "$STAGE/etc/memoryhub/config.yaml"
install -m 0644 "$SCRIPT_DIR/assets/memoryhub.desktop" "$STAGE/usr/share/applications/memoryhub.desktop"
install -m 0644 "$SCRIPT_DIR/assets/memoryhub-first-login.desktop" "$STAGE/etc/xdg/autostart/memoryhub-first-login.desktop"
install -m 0644 "$PROJECT_ROOT/desktop-client/resources/icons/logo.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/memoryhub.svg"
cp -R "$PROJECT_ROOT/agent-integration/plugin/opencode/." "$STAGE/usr/share/memoryhub/opencode/"
find "$STAGE/usr/share/memoryhub/opencode" -type f -exec chmod 0644 {} +

ln -s /opt/memoryhub/venv/bin/memoryhub "$STAGE/usr/bin/memoryhub"

cat > "$STAGE/usr/share/doc/$PACKAGE_NAME/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Kylin MemoryHub
Source: https://github.com/pyzw618/XA202612-2
License: MIT
 This package is distributed under the MIT License as declared by the upstream project.
EOF

cat > "$STAGE/usr/share/doc/$PACKAGE_NAME/README.Debian" <<EOF
Kylin MemoryHub for Debian/Kylin
================================

The package installs a per-user systemd service and an OpenCode integration.
At first desktop login, the integration is copied to ~/.config/opencode and
the service is enabled for that user. Existing user memory under
~/.local/share/MemoryHub is preserved across upgrades and removals.

Package version: $VERSION-$REVISION
EOF

sed "s/@VERSION@/$VERSION/g" "$SCRIPT_DIR/maintainer/postinst" > "$STAGE/DEBIAN/postinst"
install -m 0755 "$SCRIPT_DIR/maintainer/prerm" "$STAGE/DEBIAN/prerm"
install -m 0755 "$SCRIPT_DIR/maintainer/postrm" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst"

installed_size="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION-$REVISION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: Kylin MemoryHub Team <memoryhub@localhost>
Installed-Size: $installed_size
Depends: python3 (>= 3.11), python3-venv, python3-pip, ca-certificates, libqt5core5a, libqt5gui5, libqt5widgets5, libqt5network5, libqt5charts5, libstdc++6
Description: local memory engine and OpenCode integration for Kylin OS
 MemoryHub provides a local FastAPI memory service, Qt desktop console,
 command-line client, MCP server and an automatically configured OpenCode
 plugin. User data remains under ~/.local/share/MemoryHub.
EOF

(cd "$STAGE" && find . -type f ! -path './DEBIAN/*' -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)

echo "[4/5] Validating staged package"
test -x "$STAGE/usr/bin/memoryhub-client"
test -f "$STAGE/usr/share/memoryhub/opencode/memoryhub.plugin.mjs"
test -f "$STAGE/usr/share/memoryhub/opencode/skills/memory-awareness/SKILL.md"
test -n "$(find "$WHEELHOUSE" -maxdepth 1 -name 'kylin_memoryhub-*.whl' -print -quit)"

echo "[5/5] Creating DEB"
dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"
dpkg-deb --info "$OUTPUT"
dpkg-deb --contents "$OUTPUT" >/dev/null
(cd "$DIST_DIR" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")

echo
echo "[OK] $OUTPUT"
echo "[SHA256] $(cut -d' ' -f1 "$OUTPUT.sha256")"
