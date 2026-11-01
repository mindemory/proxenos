// How electron-builder packs the app; desktop/build.sh runs it once resources/ holds the page
// (web/) and the Python (python/). The installers land in dist/.
//
// Unsigned for now: signing needs the owner's accounts (docs/apps.md, "What only the owner can
// do"). On a Mac it's signed ad hoc, which Apple silicon needs to run it at all and which proves
// nothing about who made it. The hooks, off until their variables are set:
// - macOS: CSC_LINK and CSC_KEY_PASSWORD (the Developer ID Application certificate, as a .p12)
//   sign it with the hardened runtime; APPLE_API_KEY, APPLE_API_KEY_ID and APPLE_API_ISSUER (an
//   App Store Connect key) then notarize it. @electron/osx-sign signs every binary inside,
//   the Python's .so and .dylib files too.
// - Windows: PROXENOS_AZURE_ENDPOINT, PROXENOS_AZURE_ACCOUNT, PROXENOS_AZURE_PROFILE and
//   PROXENOS_AZURE_PUBLISHER name the Artifact Signing account, its certificate profile and the
//   publisher as the certificate has it; AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET
//   sign in to it.

const macSigned = Boolean(process.env.CSC_LINK || process.env.CSC_NAME);
const notarized = macSigned && Boolean(process.env.APPLE_API_KEY);
const azure = process.env.PROXENOS_AZURE_ACCOUNT;

module.exports = {
  appId: "io.github.mindemory.proxenos",
  productName: "Proxenos",
  copyright: "Copyright (c) 2026 Mrugank Dake",
  artifactName: "Proxenos-${version}-${arch}.${ext}",
  directories: { output: "dist" },
  files: ["main.js", "package.json"],
  extraResources: [
    { from: "resources/web", to: "web" },
    // A folder's own node_modules is always left out of a copy, so the server's comes on its own.
    { from: "resources/web/node_modules", to: "web/node_modules" },
    { from: "resources/python", to: "python" },
  ],
  icon: "resources/icon.png",
  npmRebuild: false, // the app has no packages of its own; the page's are in resources/web
  // No other program may use the app's Node, or hand it code through the environment or a
  // debugger flag: what the person allows Proxenos (Full Disk Access) stays Proxenos's.
  electronFuses: {
    runAsNode: false,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
    onlyLoadAppFromAsar: true,
  },
  mac: {
    target: [
      { target: "dmg", arch: ["arm64"] },
      { target: "zip", arch: ["arm64"] },
    ],
    category: "public.app-category.productivity",
    minimumSystemVersion: "13.0",
    extendInfo: { LSUIElement: true }, // a menu-bar app: no Dock icon until its window shows
    identity: macSigned ? undefined : "-",
    hardenedRuntime: macSigned,
    notarize: notarized,
  },
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    ...(azure
      ? {
          azureSignOptions: {
            endpoint: process.env.PROXENOS_AZURE_ENDPOINT,
            codeSigningAccountName: azure,
            certificateProfileName: process.env.PROXENOS_AZURE_PROFILE,
            publisherName: process.env.PROXENOS_AZURE_PUBLISHER,
          },
        }
      : {}),
  },
  // Installed for this person alone, with no administrator's password.
  nsis: { oneClick: true, perMachine: false },
  publish: null,
};
