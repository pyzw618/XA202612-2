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
VECTOR_SDK_SOURCE="$PROJECT_ROOT/third_party/libkysdk-vector-engine-client-nile-sp2"
VECTOR_SDK_BUILD="$BUILD_ROOT/vector-sdk"
NATIVE_LIB_DIR="$STAGE/usr/lib/memoryhub/native"
OUTPUT="$DIST_DIR/${PACKAGE_NAME}_${VERSION}-${REVISION}_${ARCH}.deb"
WHEEL_CACHE="${MEMORYHUB_WHEEL_CACHE:-}"

test -n "$VERSION" || { echo "Package version is empty" >&2; exit 2; }

case "$BUILD_ROOT" in
    "$PROJECT_ROOT"/packaging/linux/build) ;;
    *) echo "Refusing unsafe build directory: $BUILD_ROOT" >&2; exit 2 ;;
esac

for command in python3 cmake dpkg dpkg-deb ar sed find install; do
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

echo "[1/6] Building Python wheels"
if [[ -n "$WHEEL_CACHE" ]]; then
    test -d "$WHEEL_CACHE" || { echo "Wheel cache does not exist: $WHEEL_CACHE" >&2; exit 2; }
    python3 -m venv --system-site-packages "$BUILD_VENV"
    "$BUILD_VENV/bin/python" -m pip wheel --no-index --no-build-isolation \
        --find-links "$WHEEL_CACHE" --constraint "$SCRIPT_DIR/constraints.txt" \
        --wheel-dir "$WHEELHOUSE" "$PROJECT_ROOT"
else
    python3 -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/python" -m pip install --upgrade pip wheel setuptools
    "$BUILD_VENV/bin/python" -m pip wheel --constraint "$SCRIPT_DIR/constraints.txt" \
        --wheel-dir "$WHEELHOUSE" "$PROJECT_ROOT"
fi
project_wheel="$(find "$WHEELHOUSE" -maxdepth 1 -name 'kylin_memoryhub-*.whl' -print -quit)"
"$BUILD_VENV/bin/python" -c 'import sys, zipfile; required={"memoryhub/safety_rules/data/__init__.py", "memoryhub/safety_rules/data/catalog.json", "memoryhub/safety_rules/data/builtin-1.0.json"}; names=set(zipfile.ZipFile(sys.argv[1]).namelist()); missing=required-names; assert not missing, f"wheel missing resources: {sorted(missing)}"' "$project_wheel"

echo "[2/6] Building Kylin vector engine SDK bridge"
cmake -S "$VECTOR_SDK_SOURCE" -B "$VECTOR_SDK_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
    -DCMAKE_INSTALL_RPATH='$ORIGIN'
cmake --build "$VECTOR_SDK_BUILD" --parallel "$(nproc)" \
    --target kysdk-vector-engine-client-capi

echo "Checking that the native vector SDK can actually load"
LD_LIBRARY_PATH="$VECTOR_SDK_BUILD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    python3 -c 'import ctypes, sys; ctypes.CDLL(sys.argv[1])' \
    "$VECTOR_SDK_BUILD/libkysdk-vector-engine-client-capi.so"

echo "[3/6] Building Qt desktop client"
cmake -S "$PROJECT_ROOT/desktop-client" -B "$CLIENT_BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$CLIENT_BUILD" --parallel "$(nproc)"
if command -v /usr/sbin/kyexectl >/dev/null 2>&1; then
    echo "Registering freshly built executables with Kylin execution control"
    sudo /usr/sbin/kyexectl -s "$CLIENT_BUILD/memoryhub-client-api-tests"
    sudo /usr/sbin/kyexectl -s "$CLIENT_BUILD/memoryhub-client-frontend-tests"
    sudo /usr/sbin/kyexectl -s "$CLIENT_BUILD/memoryhub-client"
    if command -v /usr/sbin/kysec_netctl >/dev/null 2>&1; then
        sudo /usr/sbin/kysec_netctl --remove -a "$CLIENT_BUILD/memoryhub-client-api-tests" >/dev/null 2>&1 || true
        sudo /usr/sbin/kysec_netctl --remove -a "$CLIENT_BUILD/memoryhub-client-frontend-tests" >/dev/null 2>&1 || true
        sudo /usr/sbin/kysec_netctl --remove -a "$CLIENT_BUILD/memoryhub-client" >/dev/null 2>&1 || true
        sudo /usr/sbin/kysec_netctl --set -a "$CLIENT_BUILD/memoryhub-client-api-tests" -s allow
        sudo /usr/sbin/kysec_netctl --set -a "$CLIENT_BUILD/memoryhub-client-frontend-tests" -s allow
        sudo /usr/sbin/kysec_netctl --set -a "$CLIENT_BUILD/memoryhub-client" -s allow
    fi
fi
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
    QT_QPA_PLATFORM=offscreen ctest --test-dir "$CLIENT_BUILD" --output-on-failure \
    --timeout 120

echo "[4/6] Staging package"
install -d "$STAGE/opt/memoryhub" \
    "$STAGE/etc/memoryhub" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/lib/memoryhub" \
    "$NATIVE_LIB_DIR" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/memoryhub/opencode" \
    "$STAGE/etc/xdg/autostart" \
    "$STAGE/usr/share/doc/$PACKAGE_NAME"

install -m 0755 "$CLIENT_BUILD/memoryhub-client" "$STAGE/usr/bin/memoryhub-client"
install -m 0755 "$SCRIPT_DIR/assets/prepare-user" "$STAGE/usr/lib/memoryhub/prepare-user"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub_service_launcher" "$STAGE/usr/bin/memoryhub_service_launcher"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub_session_launcher" "$STAGE/usr/bin/memoryhub_session_launcher"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub_app_launcher" "$STAGE/usr/bin/memoryhub_app_launcher"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-mcp" "$STAGE/usr/bin/memoryhub-mcp"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-configure-opencode" "$STAGE/usr/bin/memoryhub-configure-opencode"
install -m 0644 "$SCRIPT_DIR/assets/configure_opencode.py" "$STAGE/usr/lib/memoryhub/configure_opencode.py"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-mcp-user-launcher" "$STAGE/usr/lib/memoryhub/mcp-user-launcher"
install -m 0755 "$SCRIPT_DIR/assets/memoryhub-open-agent" "$STAGE/usr/bin/memoryhub-open-agent"
install -m 0755 "$SCRIPT_DIR/assets/open-agent-shell" "$STAGE/usr/lib/memoryhub/open-agent-shell"
install -m 0644 "$SCRIPT_DIR/assets/config.yaml" "$STAGE/etc/memoryhub/config.yaml"
cp -a "$VECTOR_SDK_BUILD"/libkysdk-vector-engine-client.so* "$NATIVE_LIB_DIR/"
cp -a "$VECTOR_SDK_BUILD"/libkysdk-vector-engine-client-capi.so* "$NATIVE_LIB_DIR/"
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

The package installs a desktop-session service and an OpenCode integration.
At desktop login, the integration is copied to ~/.config/opencode and the
local service is started for that user. Existing user memory under
~/.local/share/MemoryHub is preserved across upgrades and removals.

Package version: $VERSION-$REVISION
EOF

sed -e "s/@VERSION@/$VERSION/g" -e "s/@REVISION@/$REVISION/g" \
    "$SCRIPT_DIR/maintainer/postinst" > "$STAGE/DEBIAN/postinst"
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
Depends: python3 (>= 3.11), python3-venv, python3-pip, ca-certificates, libkylin-coreai-embedding, kylin-ai-vector-engine, libgrpc++1.51t64 | libgrpc++1.51, libgrpc29t64 | libgrpc29, libprotobuf32t64 | libprotobuf32, libsqlcipher1, libqt5core5a, libqt5gui5, libqt5widgets5, libqt5network5, libqt5charts5, libstdc++6
Description: local memory engine and OpenCode integration for Kylin OS
 MemoryHub provides a local FastAPI memory service, Qt desktop console,
 command-line client, MCP server and an automatically configured OpenCode
 plugin. User data remains under ~/.local/share/MemoryHub.
EOF

(cd "$STAGE" && find . -type f ! -path './DEBIAN/*' -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)

echo "[5/6] Validating staged package"
test -x "$STAGE/usr/bin/memoryhub-client"
test -x "$STAGE/usr/bin/memoryhub_service_launcher"
test -x "$STAGE/usr/bin/memoryhub_session_launcher"
test -x "$STAGE/usr/bin/memoryhub_app_launcher"
test -x "$STAGE/usr/bin/memoryhub-open-agent"
test -x "$STAGE/usr/lib/memoryhub/open-agent-shell"
test -f "$STAGE/usr/lib/memoryhub/configure_opencode.py"
test -e "$NATIVE_LIB_DIR/libkysdk-vector-engine-client.so"
test -e "$NATIVE_LIB_DIR/libkysdk-vector-engine-client-capi.so"
test -x "$STAGE/usr/lib/memoryhub/mcp-user-launcher"
grep -q "$VERSION-$REVISION" "$STAGE/DEBIAN/postinst"
test ! -e "$STAGE/usr/lib/systemd/user/memoryhub.service"
test -f "$STAGE/usr/share/memoryhub/opencode/memoryhub.plugin.mjs"
test -f "$STAGE/usr/share/memoryhub/opencode/skills/memory-awareness/SKILL.md"
test -n "$(find "$WHEELHOUSE" -maxdepth 1 -name 'kylin_memoryhub-*.whl' -print -quit)"

echo "[6/6] Creating DEB"
dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"

# Kylin's patched dpkg-deb may append an internal `_compat` archive member
# when a package is built on Kylin itself.  That marker is intended for
# distribution-managed compatibility packages and must not leak into an
# ordinary third-party DEB.  Kylin V11 may still install native third-party
# applications through its KARE shadow environment; the package service is
# deliberately compatible with both native and KARE installation paths.
# Official Kylin signing, when configured below, is applied after this
# normalization so its signature covers the final archive.
if ar t "$OUTPUT" | grep -qx '_compat'; then
    echo "Removing Kylin-internal _compat marker from third-party DEB"
    ar d "$OUTPUT" _compat
fi

if ar t "$OUTPUT" | grep -qx '_compat'; then
    echo "Failed to remove Kylin-internal _compat marker" >&2
    exit 2
fi

if [[ -n "${KYLIN_SIGN_PRIVATE_KEY:-}" || -n "${KYLIN_SIGN_CERTIFICATE:-}" ]]; then
    if [[ -z "${KYLIN_SIGN_PRIVATE_KEY:-}" || -z "${KYLIN_SIGN_CERTIFICATE:-}" ]]; then
        echo "KYLIN_SIGN_PRIVATE_KEY and KYLIN_SIGN_CERTIFICATE must be set together" >&2
        exit 2
    fi
    command -v kylinsigntool >/dev/null 2>&1 || {
        echo "kylinsigntool is required for Kylin package signing" >&2
        exit 2
    }
    test -f "$KYLIN_SIGN_PRIVATE_KEY" || {
        echo "Kylin signing private key not found: $KYLIN_SIGN_PRIVATE_KEY" >&2
        exit 2
    }
    test -f "$KYLIN_SIGN_CERTIFICATE" || {
        echo "Kylin signing certificate not found: $KYLIN_SIGN_CERTIFICATE" >&2
        exit 2
    }
    echo "Signing DEB with the supplied Kylin developer certificate"
    kylinsigntool -a "$OUTPUT" \
        -p "$KYLIN_SIGN_PRIVATE_KEY" \
        -c "$KYLIN_SIGN_CERTIFICATE"
    kylinsigntool -v "$OUTPUT"
elif [[ "${KYLIN_REQUIRE_SIGNATURE:-false}" == "true" ]]; then
    echo "KYLIN_REQUIRE_SIGNATURE=true but no Kylin signing credentials were supplied" >&2
    exit 2
else
    echo "[WARN] DEB is unsigned; Kylin source policy must be Warning/Off for local installation"
fi

dpkg-deb --info "$OUTPUT"
dpkg-deb --contents "$OUTPUT" >/dev/null
(cd "$DIST_DIR" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")

echo
echo "[OK] $OUTPUT"
echo "[SHA256] $(cut -d' ' -f1 "$OUTPUT.sha256")"
